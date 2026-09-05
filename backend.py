import os 
from dotenv import load_dotenv
from typing import TypedDict, Annotated, Any
import uuid
import asyncio
import json
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command, interrupt
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain.chat_models import init_chat_model
from mcp_client import (
    tavily_mcp_search,
    aviation_mcp_call,
    weather_mcp_search,
    forecast_mcp_search
)

load_dotenv()

llm = init_chat_model("mistralai:mistral-small-latest")

def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url

# ==============================================================================
# 1. STATE DEFINITIONS
# ==============================================================================

class TravelState(TypedDict):
    """
    Central state schema for the LangGraph travel planning graph.
    Passed sequentially across all nodes and persisted to PostgreSQL checkpointer.
    """
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str

    # Supervisor & Input Guardrail outputs
    guardrail_allowed: bool            # True if request is travel-related, False otherwise
    guardrail_reason: str              # Explanation if request is blocked
    selected_agents: list[str]         # Specialist agents selected by supervisor
    trip_constraints: dict[str, Any]   # Extracted constraints (budget, style, origin, dates)
    supervisor_reasoning: str          # Rationale for agent selection

    # Specialist Agent outputs
    destination_city: str              # Resolved primary city name
    flight_results: str                # Route and schedule analysis from AviationStack MCP
    hotel_results: str                 # Accommodations from Tavily MCP
    weather_results: str               # Weather & 5-day forecast from FastMCP server
    budget_results: str                # Cost categories & feasibility analysis
    itinerary: str                     # Structured draft itinerary

    # Human-in-the-Loop (HITL) approval state
    approval_request: str              # Review prompt presented to human
    approved: bool                     # Whether human approved or requested changes
    human_feedback: str                # User revision instructions (if any)
    final_response: str                # Polished report synthesized after human review
    llm_calls: int                     # Total LLM invocations in this thread


# ==============================================================================
# 2. SHARED HELPERS & AGENT REGISTRY
# ==============================================================================

# Allowed specialist agents that the supervisor can dynamically activate
KNOWN_AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
}

# Fixed topological evaluation order for active specialist agents
AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]

def _llm_text(system_prompt: str, user_prompt: str) -> str:
    """Helper to invoke LLM with a system and human message pair."""
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return str(response.content)

def _json_from_llm(text: str) -> dict[str, Any]:
    """
    Extracts and parses the first complete JSON object returned by the model.
    Slices between the first '{' and the last '}', ignoring markdown backticks or preamble.
    """
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start : end + 1])


def _empty_constraints() -> dict[str, Any]:
    """Provides default empty structure for trip constraints."""
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }

# =========================
# Supervisor Agent + Input Guardrail
# =========================
def supervisor_agent(state: TravelState):
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)

    guardrail_prompt = f"""
Determine whether the following request belongs to travel planning or travel
information. Valid requests can include destinations, flights, hotels, weather,
budgets, visas, transportation, sightseeing, food, packing, or itineraries.

Block clearly unrelated requests and requests asking for harmful or illegal
instructions. Do not block a valid travel request merely because some details
are missing.

Return strict JSON only:
{{
  "allowed": true,
  "reason": ""
}}

User request:
{query}
"""

    # Fail open on parser/model errors so a temporary JSON-format issue does not
    # break the original travel-planning behavior.
    try:
        guardrail_raw = _llm_text(
            "You are the input guardrail for a travel-planning application. "
            "Return strict JSON only.",
            guardrail_prompt,
        )
        guardrail_result = _json_from_llm(guardrail_raw)
        allowed = bool(guardrail_result.get("allowed", True))
        guardrail_reason = str(guardrail_result.get("reason", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Guardrail fallback used: {exc}")
        allowed = True
        guardrail_reason = "Guardrail validation fallback allowed the request."

    if not allowed:
        reason = guardrail_reason or (
            "TripMate AI can only help with travel-planning requests. "
            "Please ask about a destination, flight, hotel, weather, budget, "
            "or itinerary."
        )
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    supervisor_prompt = f"""
You are the supervisor of a multi-agent travel-planning system.
Choose only the specialist agents needed for the request.

Available agents:
- flight_agent: flights, airports, airlines, routes, airfare, or booking advice
- hotel_agent: hotels, accommodation, neighborhoods, or places to stay
- weather_agent: weather, climate, season, forecast, or packing advice
- budget_agent: cost, affordability, price limits, or budget feasibility
- itinerary_agent: creates the integrated travel plan and must always be included

Return strict JSON only using this schema:
{{
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}

User request:
{query}
"""

    try:
        supervisor_raw = _llm_text(
            "You route work to travel specialist agents. Return strict JSON only.",
            supervisor_prompt,
        )
        parsed = _json_from_llm(supervisor_raw)
        requested_agents = parsed.get("selected_agents", [])
        selected_agents = [
            name for name in AGENT_ORDER
            if name in requested_agents and name in KNOWN_AGENTS
        ]

        # The itinerary agent integrates whichever specialist results were selected.
        if "itinerary_agent" not in selected_agents:
            selected_agents.append("itinerary_agent")

        constraints = _empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", {})
        if isinstance(parsed_constraints, dict):
            constraints.update(parsed_constraints)

        reasoning = str(parsed.get("reasoning", "")).strip()
        llm_calls += 1
    except Exception as exc:
        print(f"Supervisor fallback used: {exc}")
        # Original workflow behavior is preserved as the fallback.
        selected_agents = AGENT_ORDER.copy()
        constraints = _empty_constraints()
        reasoning = (
            "Supervisor parsing failed, so the original full travel workflow was selected as a safe fallback."
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": llm_calls,
    }    

# =========================
# Guardrail blocked response
# =========================
def guardrail_blocked_agent(state: TravelState):
    reason = state.get("final_response") or state.get("guardrail_reason") or (
        "This request was blocked by the travel input guardrail."
    )
    return {
        "final_response": reason,
        "messages": [AIMessage(content=reason)],
    }

FLIGHT_AGENT_PROMPT = """
You are an expert aviation and travel flight specialist.

User Travel Request:
{query}

Destination City: {destination_city}
Flight & Route Context from AviationStack MCP:
{route_data}

Provide a clear, practical flight guide including:
1. Recommended Departure & Arrival Airports (with 3-letter IATA codes)
2. Major Airlines Serving or Connecting on this Route
3. Estimated Flight Duration & Layover Guidelines
4. Approximate Airfare Range (Economy & Business)
5. Peak Travel Season & High-Fare Warnings
6. Key Booking Tips (Best booking window, airport transit advice)

Format the output cleanly in Markdown with bullet points and bold key details.
"""


def extract_trip_entities(query: str) -> tuple[str, str, str]:
    """
    Extracts origin IATA, destination IATA, and destination city name in a single LLM call.
    """
    extract_prompt = f"""
Identify the travel entities from this request:
Query: "{query}"

Output strictly in this format:
ORIGIN_IATA: <3-letter IATA code, default to DEL if not specified>
DEST_IATA: <3-letter IATA code for main international airport>
DEST_CITY: <Primary destination city name, e.g. Tokyo, Paris, London, Bali>
"""
    try:
        res = llm.invoke(extract_prompt).content
        dep_iata = "DEL"
        arr_iata = "TYO"
        dest_city = "Tokyo"
        for line in res.strip().split("\n"):
            if "ORIGIN_IATA:" in line:
                val = line.split("ORIGIN_IATA:")[1].strip().upper()[:3]
                if len(val) == 3 and val.isalpha():
                    dep_iata = val
            elif "DEST_IATA:" in line:
                val = line.split("DEST_IATA:")[1].strip().upper()[:3]
                if len(val) == 3 and val.isalpha():
                    arr_iata = val
            elif "DEST_CITY:" in line:
                val = line.split("DEST_CITY:")[1].strip()
                if val:
                    dest_city = val
        return dep_iata, arr_iata, dest_city
    except Exception:
        return "DEL", "HND", "Tokyo"


def flight_agent(state: TravelState):
    query = state["user_query"]
    route_details = []

    try:
        # Extract origin IATA, destination IATA, and destination city in 1 LLM call
        dep_iata, arr_iata, dest_city = extract_trip_entities(query)
        route_details.append(f"Route: {dep_iata} -> {arr_iata} ({dest_city})")

        # 1. Query AviationStack MCP for targeted route details
        try:
            routes_data = asyncio.run(
                aviation_mcp_call(
                    "list_routes",
                    {"dep_iata": dep_iata, "arr_iata": arr_iata, "limit": 5}
                )
            )
            route_details.append(f"Direct/Connecting Routes:\n{routes_data}")
        except Exception as e:
            route_details.append(f"Route lookup note: {e}")

        # 2. Query AviationStack MCP for departure schedules
        try:
            sched_data = asyncio.run(
                aviation_mcp_call(
                    "flight_arrival_departure_schedule",
                    {"airport_iata_code": dep_iata, "schedule_type": "departure", "number_of_flights": 3}
                )
            )
            route_details.append(f"Departure Schedules ({dep_iata}):\n{sched_data}")
        except Exception as e:
            route_details.append(f"Schedule lookup note: {e}")

        # 3. Synthesize flight guidance with LLM
        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            destination_city=dest_city,
            route_data="\n\n".join(route_details)
        )

        response = llm.invoke(prompt)
        flight_data = response.content

    except Exception as e:
        dest_city = "Destination"
        flight_data = f"Flight information: General route advice for {query} (Details: {str(e)})"

    return {
        "destination_city": dest_city,
        "flight_results": flight_data,
        "messages": [
            AIMessage(
                content="Flight recommendations generated"
            )
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# =========================
# Hotel Agent
# =========================

def hotel_agent(state: TravelState):
    dest_city = state.get("destination_city") or state["user_query"]
    query = f"Best hotels and accommodations in {dest_city}"
    hotel_results = asyncio.run(tavily_mcp_search(query))

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# =========================
# Weather Agent
# =========================

def weather_agent(state: TravelState):
    city = state.get("destination_city") or state["user_query"]

    try:
        weather_data = asyncio.run(
            weather_mcp_search(city)
        )
        forecast_data = asyncio.run(
            forecast_mcp_search(city)
        )
        weather_summary = f"Current Weather in {city}:\n{weather_data}\n\nForecast:\n{forecast_data}"
    except Exception as e:
        weather_summary = f"Weather information unavailable for {city}: {str(e)}"

    return {
        "weather_results": weather_summary,
        "messages": [
            AIMessage(
                content="Weather information fetched"
            )
        ]
    }

# =========================
# Budget Agent - new specialist
# =========================
def budget_agent(state: TravelState):
    prompt = f"""
Analyze whether this trip is realistic for the user's budget.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', '')}

Hotel Results:
{state.get('hotel_results', '')}

Weather Results:
{state.get('weather_results', '')}

Return:
1. Estimated cost categories
2. Budget risk areas
3. Money-saving suggestions
4. Overall feasibility

If exact live prices are unavailable, clearly label estimates as approximate.
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are a practical travel budget analyst."),
            HumanMessage(content=prompt),
        ]
    )

    return {
        "budget_results": response.content,
        "messages": [AIMessage(content="Budget assessment generated.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# =========================
# Itinerary Agent
# =========================

def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{state.get('flight_results', '')}

Hotel Results:
{state.get('hotel_results', '')}

Weather Results:
{state.get('weather_results', '')}

Budget Results:
{state.get('budget_results', '')}

Make the itinerary practical, budget-aware, and easy to follow.
Create a clear draft that is ready for human review.
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are an expert travel planner."),
            HumanMessage(content=prompt),
        ]
    )

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create the "
        "final polished plan, or provide feedback for revision."
    )

    return {
        "itinerary": response.content,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }

# ==============================================================================
# 5. HUMAN-IN-THE-LOOP (HITL) APPROVAL NODE
# ==============================================================================

def human_approval_agent(state: TravelState):
    """
    Human-in-the-Loop checkpoint node.
    
    Calls LangGraph's interrupt() to pause execution and store the checkpoint in PostgreSQL.
    CRITICAL: Never wrap interrupt() in a try/except block because LangGraph uses a special
    control-flow exception internally to halt execution and return control to the caller.
    
    When resumed via Command(resume={"approved": ..., "feedback": ...}), interrupt()
    unblocks and evaluates to the dictionary passed in the resume command.
    """
    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )

    approved = bool(review.get("approved", False))
    human_feedback = str(review.get("feedback", "")).strip()

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [AIMessage(content="Human approval step completed.")],
    }


# ==============================================================================
# 6. FINAL SYNTHESIZER AGENT
# ==============================================================================

def final_agent(state: TravelState):
    """
    Consolidates findings from all active specialist agents and the human review.
    If the human requested adjustments, applies the feedback; if approved, preserves decisions.
    Produces the final structured Markdown report for the user.
    """
    if state.get("approved", False):
        review_instruction = (
            "The user approved the draft. Preserve its decisions while polishing it."
        )
    else:
        review_instruction = f"""
The user requested a revision. Apply this feedback carefully:
{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}
"""

    final_prompt = f"""
Generate the final travel response for the user.

Human Review:
{review_instruction}

User Request:
{state['user_query']}

Supervisor Constraints:
{state.get('trip_constraints', {})}

Flights:
{state.get('flight_results', '')}

Hotels:
{state.get('hotel_results', '')}

Weather:
{state.get('weather_results', '')}

Budget Analysis:
{state.get('budget_results', '')}

Draft Itinerary:
{state.get('itinerary', '')}

Format the final answer beautifully using these sections:
1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Important:
- Be clear and practical.
- Mention that live flight APIs may not provide ticket prices when pricing is unavailable.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
- Incorporate the human feedback when revision was requested.
"""

    response = llm.invoke(
        [
            SystemMessage(
                content="You are a professional AI travel booking assistant."
            ),
            HumanMessage(content=final_prompt),
        ]
    )

    return {
        "final_response": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


# ==============================================================================
# 7. DYNAMIC SUPERVISOR ROUTING LOGIC
# ==============================================================================

ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent",
}


def _selected_agents(state: TravelState) -> list[str]:
    """Filters AGENT_ORDER to keep only the agents selected by the supervisor."""
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent in selected]


def route_from_supervisor(state: TravelState) -> str:
    """
    Initial conditional router:
    - If guardrail blocked the query -> routes directly to guardrail_blocked node.
    - Otherwise -> routes to the first active specialist agent in AGENT_ORDER.
    """
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"

    selected = _selected_agents(state)
    return selected[0] if selected else "itinerary_agent"


def route_after_agent(current_agent: str):
    """
    Higher-order routing function:
    Returns a conditional edge router that finds the next active agent after `current_agent`
    in AGENT_ORDER. If no more specialists remain, routes to `itinerary_agent`.
    """
    def route(state: TravelState) -> str:
        selected = _selected_agents(state)
        current_index = AGENT_ORDER.index(current_agent)

        for next_agent in AGENT_ORDER[current_index + 1 :]:
            if next_agent in selected:
                return next_agent

        return "itinerary_agent"

    return route


# ==============================================================================
# 8. STATE GRAPH CONSTRUCTION
# ==============================================================================

graph = StateGraph(TravelState)

# Register graph nodes
graph.add_node("supervisor", supervisor_agent)
graph.add_node("guardrail_blocked", guardrail_blocked_agent)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("budget_agent", budget_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("human_approval", human_approval_agent)
graph.add_node("final_agent", final_agent)

# Entry point: start at supervisor
graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route_from_supervisor, ROUTE_MAP)

# Dynamic specialist edges: sequentially hop between active agents
graph.add_conditional_edges(
    "flight_agent", route_after_agent("flight_agent"), ROUTE_MAP
)
graph.add_conditional_edges(
    "hotel_agent", route_after_agent("hotel_agent"), ROUTE_MAP
)
graph.add_conditional_edges(
    "weather_agent", route_after_agent("weather_agent"), ROUTE_MAP
)
graph.add_conditional_edges(
    "budget_agent", route_after_agent("budget_agent"), ROUTE_MAP
)

# Itinerary synthesizes draft -> pauses at human_approval -> polishes at final_agent
graph.add_edge("itinerary_agent", "human_approval")
graph.add_edge("human_approval", "final_agent")
graph.add_edge("final_agent", END)
graph.add_edge("guardrail_blocked", END)


# ==============================================================================
# 9. POSTGRES CHECKPOINTER & EXECUTION LIFECYCLE
# ==============================================================================

DATABASE_URL = get_database_url()
travel_graph = graph


def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extracts the payload dict from LangGraph's __interrupt__ attribute if the graph paused.
    """
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None

    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value": payload}


def _serialize_result(
    result: dict[str, Any],
    thread_id: str,
) -> dict[str, Any]:
    """
    Prepares a clean JSON-serializable dictionary for FastAPI HTTP responses.
    Accurately reflects whether the workflow is paused awaiting human approval.
    """
    messages = result.get("messages", [])
    last_message = messages[-1].content if messages else ""
    answer = result.get("final_response") or last_message
    interrupt_payload = _interrupt_payload(result)

    if interrupt_payload:
        answer = interrupt_payload.get("draft_itinerary") or result.get(
            "itinerary", ""
        )

    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "itinerary": (
            interrupt_payload.get("draft_itinerary", "")
            if interrupt_payload
            else result.get("itinerary", "")
        ),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


def run_travel_agent(user_input: str, thread_id: str | None = None):
    """
    Initiates a new travel-planning workflow.
    
    1. Generates or reuses a unique thread_id for conversation state isolation.
    2. Opens a fresh connection to the PostgreSQL checkpointer.
    3. Invokes the LangGraph state graph starting at supervisor_agent.
    4. Automatically pauses at human_approval_agent when interrupt() is encountered.
    5. Returns the serialized partial state (draft itinerary and requires_approval=True).
    """
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()
        app_workflow = graph.compile(checkpointer=checkpointer)

        result = app_workflow.invoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_query": user_input,
                "guardrail_allowed": True,
                "guardrail_reason": "",
                "selected_agents": [],
                "trip_constraints": _empty_constraints(),
                "supervisor_reasoning": "",
                "flight_results": "",
                "hotel_results": "",
                "weather_results": "",
                "budget_results": "",
                "itinerary": "",
                "approval_request": "",
                "approved": False,
                "human_feedback": "",
                "final_response": "",
                "llm_calls": 0,
            },
            config=config,
        )

        return _serialize_result(result, thread_id)


def resume_travel_agent(
    thread_id: str,
    approved: bool,
    feedback: str = "",
):
    """
    Resumes a paused travel-planning workflow after human review.
    
    1. Loads the paused state snapshot from PostgreSQL using thread_id.
    2. Sends Command(resume={"approved": approved, "feedback": feedback}) to unblock interrupt().
    3. human_approval_agent receives the payload and passes control to final_agent.
    4. final_agent incorporates feedback or preserves decisions to synthesize the final guide.
    5. Returns the completed, polished travel plan.
    """
    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}

    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()
        app_workflow = graph.compile(checkpointer=checkpointer)

        result = app_workflow.invoke(
            Command(
                resume={
                    "approved": approved,
                    "feedback": feedback.strip(),
                }
            ),
            config=config,
        )

        return _serialize_result(result, thread_id)


def get_travel_session(thread_id: str):
    """
    Retrieves the latest state of a saved travel conversation from the PostgreSQL checkpointer.
    Used by frontend on page load or refresh to seamlessly restore history and active sessions.
    """
    if not thread_id:
        return None

    config = {"configurable": {"thread_id": thread_id}}

    try:
        with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
            app_workflow = graph.compile(checkpointer=checkpointer)
            state = app_workflow.get_state(config)

            if not state or not state.values:
                return None

            values = state.values
            messages = values.get("messages", [])
            last_message = messages[-1].content if messages else ""
            answer = values.get("final_response") or last_message

            # Check if there is an active interrupt pending
            interrupt_payload = None
            if hasattr(state, "tasks") and state.tasks:
                for task in state.tasks:
                    if hasattr(task, "interrupts") and task.interrupts:
                        first_int = task.interrupts[0]
                        interrupt_payload = getattr(first_int, "value", first_int)
                        break

            if interrupt_payload:
                answer = interrupt_payload.get("draft_itinerary") or values.get("itinerary", "")

            return {
                "thread_id": thread_id,
                "answer": answer,
                "requires_approval": interrupt_payload is not None,
                "approval_request": (
                    interrupt_payload.get("approval_request", "")
                    if interrupt_payload
                    else values.get("approval_request", "")
                ),
                "flight_results": values.get("flight_results", ""),
                "hotel_results": values.get("hotel_results", ""),
                "weather_results": values.get("weather_results", ""),
                "budget_results": values.get("budget_results", ""),
                "itinerary": values.get("itinerary", ""),
                "selected_agents": values.get("selected_agents", []),
                "trip_constraints": values.get("trip_constraints", {}),
                "supervisor_reasoning": values.get("supervisor_reasoning", ""),
                "guardrail_allowed": values.get("guardrail_allowed", True),
                "guardrail_reason": values.get("guardrail_reason", ""),
                "approved": values.get("approved"),
                "human_feedback": values.get("human_feedback", ""),
                "llm_calls": values.get("llm_calls", 0),
            }
    except Exception as exc:
        print(f"Error retrieving travel session {thread_id}: {exc}")
        return None