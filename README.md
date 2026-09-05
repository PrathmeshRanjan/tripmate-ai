# Voyagent AI: Multi-Agent Travel Planner

Live Deployment: [https://tripmate-ai-546l.onrender.com/](https://tripmate-ai-546l.onrender.com/)

---

## Overview

Voyagent AI is an autonomous, multi-agent travel planning system built with LangGraph, Model Context Protocol (MCP), FastAPI, and PostgreSQL. It transforms natural language travel requests into structured itineraries by coordinating specialized AI agents. Each agent handles a distinct stage of travel planning—including flight route discovery, accommodation research, local weather analysis, activity scheduling, and synthesis—while persisting state and conversation checkpoints to a PostgreSQL database.

---

## System Architecture

The application implements a directed state graph workflow where incoming queries are validated by a supervisor agent, conditionally routed through active specialist nodes, and paused for human inspection. Users can request revisions across multiple cycles before final synthesis.

```mermaid
flowchart TD
    User([User Request]) --> API[FastAPI: POST /api/travel]
    API --> Supervisor[Supervisor Agent & Guardrail]
    
    Supervisor -->|Invalid Travel Request| GuardrailBlocked[Guardrail Blocked Node]
    GuardrailBlocked --> END([End / Return Rejection])
    
    Supervisor -->|Valid Request & Dynamic Routing| Specialists{Dynamic Specialist Routing}
    
    Specialists -.-> FlightAgent[Flight Agent - AviationStack MCP]
    Specialists -.-> HotelAgent[Hotel Agent - Tavily Search MCP]
    Specialists -.-> WeatherAgent[Weather Agent - FastMCP Server]
    Specialists -.-> BudgetAgent[Budget Feasibility Agent]
    
    FlightAgent -.-> HotelAgent
    HotelAgent -.-> WeatherAgent
    WeatherAgent -.-> BudgetAgent
    BudgetAgent -.-> ItineraryAgent[Itinerary Agent]
    
    ItineraryAgent -->|Draft Itinerary| HumanApproval[Human-in-the-Loop Checkpoint: interrupt]
    
    HumanApproval -->|POST /api/travel/resume: approved=False| RevisionAgent[Revision Agent]
    RevisionAgent -->|Updated Draft Itinerary| HumanApproval
    
    HumanApproval -->|POST /api/travel/resume: approved=True| FinalAgent[Final Synthesizer Agent]
    FinalAgent --> StateSave[(PostgreSQL Checkpoint Storage)]
    StateSave --> END
```

---

## Specialized Agents & Workflow Lifecycle

### 1. Supervisor Agent & Input Guardrail (`supervisor_agent`)
* **Input Guardrail**: Evaluates whether incoming requests are legitimate travel planning queries. Off-topic, harmful, or adversarial prompts are rejected early to conserve LLM tokens and execution resources.
* **Constraint Extraction**: Extracts structured parameters including origin city, destination city, trip duration, budget bracket, passenger counts, and travel preferences.
* **Dynamic Agent Selection**: Identifies which specialist agents are strictly required for the query and populates `state["selected_agents"]`.

### 2. Flight Agent (`flight_agent`)
* **Role**: Resolves origin and destination airport IATA codes and queries flight schedules.
* **Tool Integration**: Connects to the AviationStack MCP server over stdio to query `list_routes` and `flight_arrival_departure_schedule`.
* **Output**: Extracts viable flight routes, airline options, transit durations, and travel advice.

### 3. Hotel Agent (`hotel_agent`)
* **Role**: Researches accommodations suited to the destination, group style, and budget constraints.
* **Tool Integration**: Connects to the Tavily Remote MCP server using HTTP transport (`streamable_http`) for accommodation availability, neighborhood safety, and guest ratings.
* **Output**: Delivers categorized stay recommendations across budget, mid-range, and premium tiers.

### 4. Weather Agent (`weather_agent`)
* **Role**: Retrieves real-time weather conditions and multi-day meteorological forecasts.
* **Tool Integration**: Invokes a custom FastMCP weather server (`weather_custom_mcp_server.py`) over stdio that queries OpenWeatherMap endpoints.
* **Output**: Reports temperature, precipitation risk, wind speed, and weather-specific packing recommendations.

### 5. Budget Agent (`budget_agent`)
* **Role**: Evaluates the economic feasibility of the requested itinerary.
* **Output**: Provides categorized cost estimates (flights, accommodations, dining, activities, local transit), flags budget risk areas, and suggests cost-saving alternatives.

### 6. Itinerary Agent (`itinerary_agent`)
* **Role**: Consolidates findings from active specialists into a day-by-day draft schedule.
* **Output**: Emits a structured draft itinerary ready for human inspection.

### 7. Human-in-the-Loop Review Node (`human_approval_agent`)
* **Mechanism**: Calls LangGraph's `interrupt()` function to suspend workflow execution and persist state to PostgreSQL.
* **Action**: Returns the draft itinerary and pauses until the user submits feedback or approval via `POST /api/travel/resume`.

### 8. Revision Agent (`revision_agent`)
* **Mechanism**: Triggered when the human reviewer requests modifications (`approved = False`).
* **Role**: Ingests specific user feedback, applies modifications to the draft itinerary, and cycles back to `human_approval_agent` for re-inspection.
* **Iterative Loop**: Allows users to refine the plan over multiple revision turns until fully satisfied.

### 9. Final Synthesizer Agent (`final_agent`)
* **Role**: Triggered once the human approves the plan (`approved = True`).
* **Output**: Formulates the final comprehensive travel document with trip summary, transit details, hotel suggestions, daily activities, weather packing advice, and final recommendations.

### 10. Guardrail Blocked Node (`guardrail_blocked_agent`)
* **Role**: Handles off-topic or prohibited queries, returning an explanation and terminating immediately at `END`.

---

## Dynamic Topological Routing Mechanics

Rather than enforcing a static pipeline where every agent must execute regardless of user intent, Voyagent uses dynamic topological dispatching:

```python
AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]

ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent",
}
```

* **Higher-Order Edge Router (`route_after_agent`)**: Generates a conditional routing closure that inspects `state["selected_agents"]` and skips inactive specialists directly to the next active agent.
* **Approval Router (`route_after_approval`)**: Directs execution to `final_agent` upon approval, or to `revision_agent` upon revision request, enabling multi-round feedback loops.

---

## State Schema and Database Persistence

### Unified State Schema (`TravelState`)

```python
class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str

    # Supervisor & Input Guardrail outputs
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # Specialist Agent outputs
    destination_city: str
    flight_results: str
    hotel_results: str
    weather_results: str
    budget_results: str
    itinerary: str

    # Human-in-the-Loop (HITL) approval & revision state
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str
    llm_calls: int
```

### Persistence Architecture

1. **Database Checkpointing**: State snapshots are serialized after each node execution and stored in PostgreSQL (`PostgresSaver`). This guarantees conversation memory across multi-turn queries.
2. **Connection Lifecycle**: Utilizes `PostgresSaver.from_conn_string()` with `prepare_threshold=0` and `autocommit=True` to maintain compatibility with serverless connection poolers and prevent dropped idle socket errors.
3. **Frontend Session Synchronization**: Session identifiers (`thread_id`) are maintained in browser storage (`localStorage`). When returning to the site or refreshing the page, the client calls `GET /api/travel/session/{thread_id}` to retrieve and restore saved state from the database without re-executing LLM calls.
4. **Trip History Drawer**: Stores and lists past generated plans locally with direct deep-linking to corresponding database checkpoints.

---

## Model Fallback Strategy

To prevent interruption from upstream API rate limits (such as HTTP 429), quota exhaustion, or connectivity issues, Voyagent AI implements an automatic fallback mechanism using LangChain's `with_fallbacks`:

* **Primary Model**: Defaults to `mistralai:mistral-small-latest` via `MISTRAL_API_KEY`.
* **Fallback Model**: Defaults to Google Gemini `gemini-2.5-flash` via `GOOGLE_API_KEY`.
* **Behavior**: If the primary model raises an exception (such as a 429 rate limit or network timeout), the node automatically catches the failure and immediately routes the request to Google Gemini without interrupting execution or losing state.

---

## Technology Stack

### Backend & AI Agents
* **Python 3.13+**: Core runtime environment.
* **FastAPI**: Asynchronous web framework exposing REST endpoints and serving static assets.
* **Uvicorn**: ASGI web server implementation.
* **LangGraph & LangChain Core**: Multi-agent state graph orchestration, node routing, and message reducers.
* **Mistral AI & Google Gemini**: Language model providers with automatic fallback from Mistral to Gemini on rate limiting (HTTP 429) or service interruption.
* **Psycopg 3 & Psycopg Pool**: PostgreSQL database adapter supporting connection pooling and binary serialization.
* **PostgreSQL / Neon**: Serverless relational database for persistent checkpoint storage.

### Model Context Protocol (MCP) Ecosystem
* **MultiServerMCPClient (`langchain-mcp-adapters`)**: Unified client managing multiple concurrent MCP server connections.
* **FastMCP (`mcp.server.fastmcp`)**: High-level framework powering the custom Weather MCP server.
* **AviationStack MCP (`aviationstack-mcp`)**: Local stdio MCP server for live route and schedule discovery.
* **Tavily MCP**: Remote HTTP MCP server (`streamable_http`) for accommodation and web search.

### External APIs
* **AviationStack API**: Live flight schedules, route databases, and airport timetables.
* **Tavily Search API**: Search engine optimized for LLMs to retrieve live hotel and travel information.
* **OpenWeatherMap API**: Current weather conditions and 5-day / 3-hour forecasts.

### Frontend
* **HTML5 & Modern CSS**: Glassmorphic dark interface with responsive layouts and CSS custom properties.
* **Vanilla JavaScript (ES6+)**: Client-side state controller, asynchronous request lifecycle management, and dynamic DOM rendering.
* **Marked.js**: Client-side Markdown parser for rendering structured itineraries.
* **html2pdf.js**: Client-side PDF generation engine with print formatting.

### Infrastructure & Containerization
* **Docker**: Containerized deployment using `python:3.13-slim`.
* **Render**: Cloud hosting platform running the containerized service.

---

## Repository Structure

```text
Voyagent/
├── app.py                         # FastAPI application, routes, and exception handlers
├── backend.py                     # LangGraph graph definition, state schema, and agents
├── mcp_client.py                  # Multi-server MCP client (Tavily HTTP + AviationStack stdio + Weather stdio)
├── weather_custom_mcp_server.py   # Custom FastMCP weather server (OpenWeatherMap)
├── Dockerfile                     # Container image build definition (Python 3.13)
├── .dockerignore                  # Excluded patterns for Docker build context
├── pyproject.toml                 # Project metadata and package dependencies
├── requirements.txt               # Locked dependency list
├── .env.example                   # Template for environment configuration
├── templates/
│   └── index.html                 # Jinja2 HTML layout and structural components
└── static/
    ├── style.css                  # Design system, layout, and print styles
    └── script.js                  # Client-side controller and session logic
```

---

## Installation and Local Setup

### Prerequisites
* Python 3.13 or higher
* Git
* Access to a PostgreSQL database (e.g., Neon, AWS RDS, or local PostgreSQL)

### 1. Clone the Repository
```bash
git clone https://github.com/PrathmeshRanjan/Voyagent.git
cd Voyagent
```

### 2. Set Up Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the project root based on the following template:

```env
# Language Model Providers
MISTRAL_API_KEY=your_mistral_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here

# Optional Model Configuration (with automatic fallback to Gemini)
PRIMARY_MODEL=mistralai:mistral-small-latest
FALLBACK_MODEL=gemini-2.5-flash

# Search, Flight, and Weather Tools (MCP)
TAVILY_API_KEY=your_tavily_api_key_here
AVIATION_STACK_API_KEY=your_aviationstack_api_key_here
OPENWEATHER_API_KEY=your_openweather_api_key_here

# Persistence Database
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require

# Optional LangSmith Tracing
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=voyagent-ai
```

### 5. Run the Application
```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

The application will be accessible at `http://127.0.0.1:8000`.

---

## Docker Setup

### 1. Build the Docker Image
```bash
docker build -t voyagent-ai .
```

### 2. Run the Container
```bash
docker run -d -p 8000:8000 --env-file .env --name voyagent-app voyagent-ai
```

---

## API Reference

### 1. Generate Travel Plan
* **Endpoint**: `POST /api/travel`
* **Content-Type**: `application/json`
* **Request Body**:
  ```json
  {
    "message": "Plan a 5-day trip to Tokyo from New Delhi in October",
    "thread_id": "optional-existing-thread-id"
  }
  ```
* **Response**:
  ```json
  {
    "success": true,
    "thread_id": "user_e23a91bc74d84f1a",
    "answer": "# Draft Tokyo Itinerary...",
    "requires_approval": true,
    "approval_request": "Please review the generated draft itinerary...",
    "flight_results": "...",
    "hotel_results": "...",
    "weather_results": "...",
    "budget_results": "...",
    "itinerary": "...",
    "llm_calls": 5
  }
  ```

### 2. Resume / Approve Travel Plan (Human-in-the-Loop)
* **Endpoint**: `POST /api/travel/resume`
* **Content-Type**: `application/json`

**Case A: Request Revisions (`approved: false`)**
* **Request Body**:
  ```json
  {
    "thread_id": "user_e23a91bc74d84f1a",
    "approved": false,
    "feedback": "Prefer boutique traditional ryokans and add a day trip to Mount Fuji."
  }
  ```
* **Response (Updated Draft, Paused Again)**:
  ```json
  {
    "success": true,
    "thread_id": "user_e23a91bc74d84f1a",
    "answer": "# Revised Tokyo Itinerary with Mount Fuji...",
    "requires_approval": true,
    "approval_request": "Revision applied: 'Prefer boutique traditional ryokans and add a day trip to Mount Fuji.'. Please review the updated draft.",
    "itinerary": "..."
  }
  ```

**Case B: Approve Itinerary (`approved: true`)**
* **Request Body**:
  ```json
  {
    "thread_id": "user_e23a91bc74d84f1a",
    "approved": true,
    "feedback": ""
  }
  ```
* **Response (Finalized Plan)**:
  ```json
  {
    "success": true,
    "thread_id": "user_e23a91bc74d84f1a",
    "answer": "# Final Tokyo Travel Guide...",
    "requires_approval": false,
    "approved": true,
    "final_response": "..."
  }
  ```

### 3. Retrieve Saved Session
* **Endpoint**: `GET /api/travel/session/{thread_id}`
* **Response**:
  ```json
  {
    "success": true,
    "thread_id": "user_e23a91bc74d84f1a",
    "user_query": "Plan a 7-day trip to Tokyo from New Delhi in October under $2500",
    "answer": "# Draft or Final Plan...",
    "requires_approval": true,
    "flight_results": "...",
    "hotel_results": "...",
    "weather_results": "...",
    "budget_results": "...",
    "itinerary": "..."
  }
  ```

### 4. Health Check
* **Endpoint**: `GET /health`
* **Response**:
  ```json
  {
    "status": "ok",
    "message": "AI Travel Planner API is running"
  }
  ```

---

## License

This project is licensed under the MIT License.