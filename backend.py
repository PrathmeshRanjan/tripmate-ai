import os 
from dotenv import load_dotenv
from typing import TypedDict, Annotated
import uuid
import asyncio
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.postgres import PostgresSaver
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

llm = init_chat_model("mistralai:mistral-medium-latest")

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

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
    destination_city: str
    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str
    llm_calls: int


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
# Itinerary Agent
# =========================

def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Flight Results:
{state['flight_results']}

Hotel Results:
{state['hotel_results']}

Weather Results:
{state['weather_results']}

Make the itinerary practical, budget-aware, and easy to follow.
"""

    response = llm.invoke([
        SystemMessage(content="You are an expert travel planner."),
        HumanMessage(content=prompt)
    ])

    return {
        "itinerary": response.content,
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


# =========================
# Final Response Agent
# =========================

def final_agent(state: TravelState):
    final_prompt = f"""
Generate the final travel response for the user.

User Request:
{state['user_query']}

Flights:
{state['flight_results']}

Hotels:
{state['hotel_results']}

Itinerary:
{state['itinerary']}

Weather Results:
{state['weather_results']}

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
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
"""

    response = llm.invoke([
        SystemMessage(content="You are a professional AI travel booking assistant."),
        HumanMessage(content=final_prompt)
    ])

    return {
        "messages": [response],
        "llm_calls": state.get("llm_calls", 0) + 1
    }    

graph = StateGraph(TravelState)

graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node('weather_agent', weather_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "flight_agent")
graph.add_edge("flight_agent", "hotel_agent")
graph.add_edge("hotel_agent", "weather_agent")
graph.add_edge("weather_agent", "itinerary_agent")
graph.add_edge("itinerary_agent", "final_agent")
graph.add_edge("final_agent", END)

DATABASE_URL = get_database_url()


def run_travel_agent(user_input: str, thread_id: str | None = None):
    """
    Executes the multi-agent travel planning graph with persistent PostgreSQL checkpointer.
    Uses PostgresSaver.from_conn_string context manager to ensure fresh, live database connections.
    """
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    # Open a fresh, reliable connection to Postgres/Neon for each request
    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        checkpointer.setup()
        app_workflow = graph.compile(checkpointer=checkpointer)

        result = app_workflow.invoke(
            {
                "messages": [
                    HumanMessage(content=user_input)
                ],
                "user_query": user_input,
                "destination_city": "",
                "flight_results": "",
                "hotel_results": "",
                "weather_results": "",
                "itinerary": "",
                "llm_calls": 0
            },
            config=config
        )

        final_answer = result["messages"][-1].content

        return {
            "thread_id": thread_id,
            "answer": final_answer,
            "flight_results": result.get("flight_results", ""),
            "hotel_results": result.get("hotel_results", ""),
            "weather_results": result.get("weather_results", ""),
            "itinerary": result.get("itinerary", ""),
            "llm_calls": result.get("llm_calls", 0),
        }


def get_travel_session(thread_id: str):
    """
    Retrieves the latest state of a saved travel conversation from PostgreSQL checkpointer.
    """
    if not thread_id:
        return None

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        app_workflow = graph.compile(checkpointer=checkpointer)
        state = app_workflow.get_state(config)

        if not state or not state.values:
            return None

        values = state.values
        messages = values.get("messages", [])
        final_answer = messages[-1].content if messages else ""

        return {
            "thread_id": thread_id,
            "answer": final_answer,
            "user_query": values.get("user_query", ""),
            "flight_results": values.get("flight_results", ""),
            "hotel_results": values.get("hotel_results", ""),
            "weather_results": values.get("weather_results", ""),
            "itinerary": values.get("itinerary", ""),
            "llm_calls": values.get("llm_calls", 0),
        }