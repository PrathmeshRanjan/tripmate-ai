# Voyagent AI: Multi-Agent Travel Planner

Live Deployment: [https://tripmate-ai-546l.onrender.com/](https://tripmate-ai-546l.onrender.com/)

---

## Overview

Voyagent AI is an autonomous, multi-agent travel planning system built with LangGraph, Model Context Protocol (MCP), FastAPI, and PostgreSQL. It transforms natural language travel requests into structured itineraries by coordinating specialized AI agents. Each agent handles a distinct stage of travel planning—including flight route discovery, accommodation research, local weather analysis, activity scheduling, and synthesis—while persisting state and conversation checkpoints to a PostgreSQL database.

---

## System Architecture

The application implements a directed graph workflow where state is evaluated by a supervisor agent, conditionally routed through specialized specialist nodes, and paused for human review before final synthesis.

```mermaid
flowchart TD
    User([User Request]) --> API[FastAPI Endpoint: /api/travel]
    API --> Supervisor[Supervisor & Input Guardrail]
    
    Supervisor -->|Invalid Travel Request| GuardrailBlocked[Guardrail Blocked Node]
    GuardrailBlocked --> END([End / Return Reason])
    
    Supervisor -->|Valid Request & Agent Routing| FlightAgent[Flight Agent - MCP]
    FlightAgent --> HotelAgent[Hotel Agent - MCP]
    HotelAgent --> WeatherAgent[Weather Agent - FastMCP]
    WeatherAgent --> BudgetAgent[Budget Agent]
    BudgetAgent --> ItineraryAgent[Itinerary Agent]
    
    ItineraryAgent -->|Draft Itinerary| HumanApproval[Human-in-the-Loop: interrupt]
    HumanApproval -->|POST /api/travel/resume| FinalAgent[Final Synthesizer Agent]
    FinalAgent --> StateSave[(PostgreSQL Checkpoint Storage)]
    StateSave --> Response[JSON Response / Markdown Report]
    Response --> UI[Web Interface & PDF Generator]
```

---

## Specialized Agents & Workflow

### 1. Supervisor Agent & Input Guardrail (`supervisor_agent`)
* **Input Guardrail**: Validates whether requests belong to travel planning. Blocks off-topic or harmful inputs early to conserve LLM tokens.
* **Dynamic Routing**: Parses user constraints (origin, destination, budget, style) and selects the subset of specialist agents required for the trip.

### 2. Flight Agent (`flight_agent`)
* **Role**: Resolves origin and destination IATA codes and queries the AviationStack MCP server (`list_routes` and `flight_arrival_departure_schedule` via stdio).
* **Output**: Extracts route options, airline recommendations, expected durations, and airfare guidance.

### 3. Hotel Agent (`hotel_agent`)
* **Role**: Evaluates accommodations matching destination and budget tiers.
* **Tool Integration**: Queries the Tavily Remote MCP server (`streamable_http` transport) for hotel ratings, safety, and price ranges.
* **Output**: Curates recommended stays across budget, mid-tier, and premium brackets.

### 4. Weather Agent (`weather_agent`)
* **Role**: Retrieves real-time weather metrics and 5-day forecasts for the destination city.
* **Tool Integration**: Calls the custom Weather FastMCP server (`weather_custom_mcp_server.py`) over stdio to query OpenWeatherMap endpoints.
* **Output**: Provides current temperature, sky conditions, wind speed, and multi-day forecast checkpoints.

### 5. Budget Agent (`budget_agent`)
* **Role**: Analyzes the feasibility of the trip against user budget constraints.
* **Output**: Identifies cost drivers, budget risk areas, money-saving alternatives, and overall affordability assessments.

### 6. Itinerary Agent (`itinerary_agent`)
* **Role**: Synthesizes flight timings, hotel base locations, weather forecasts, and budget constraints into a structured draft schedule.
* **Output**: Emits a draft itinerary prepared for human review.

### 7. Human-in-the-Loop Review (`human_approval_agent`)
* **Mechanism**: Calls LangGraph's `interrupt()` to pause graph execution and persist state to PostgreSQL.
* **Action**: Presents the draft plan to the user in the UI, allowing one-click approval or revision with specific feedback via `POST /api/travel/resume`.

### 8. Final Synthesizer Agent (`final_agent`)
* **Role**: Incorporates human review decisions and feedback into a polished, comprehensive Markdown travel guide with packing tips, schedules, and budgets.

---

## State Management and Persistence

The multi-agent graph operates on a shared typed dictionary (`TravelState`) containing:

```python
class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str

    # Supervisor & Guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # Budget & Human-in-the-Loop state
    budget_results: str
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str

    # Travel domain state
    destination_city: str
    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str
    llm_calls: int
```

### Persistence Architecture

1. **Database Checkpointing**: State snapshots are serialized after each node execution and stored in PostgreSQL (`PostgresSaver`). This guarantees conversation memory across multi-turn queries.
2. **Connection Lifecycle**: Utilizes `PostgresSaver.from_conn_string()` with `prepare_threshold=0` and `autocommit=True` to maintain compatibility with serverless connection poolers and prevent dropped idle socket errors.
3. **Frontend Session Synchronization**: Session identifiers (`thread_id`) are maintained in browser storage (`localStorage`). When returning to the site or refreshing the page, the client calls `GET /api/travel/session/{thread_id}` to retrieve and restore saved state from the database without re-executing LLM calls.
4. **Trip History Drawer**: Stores and lists past generated plans locally with direct deep-linking to corresponding database checkpoints.

---

## Technology Stack

### Backend & AI Agents
* **Python 3.13+**: Core runtime environment.
* **FastAPI**: Asynchronous web framework exposing REST endpoints and serving static assets.
* **Uvicorn**: ASGI web server implementation.
* **LangGraph & LangChain Core**: Multi-agent state graph orchestration, node routing, and message reducers.
* **Mistral AI & Google Gemini**: Language model providers for entity extraction, reasoning, and synthesis.
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
GOOGLE_API_KEY=your_gemini_api_key_here
MISTRAL_API_KEY=your_mistral_api_key_here

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

### 2. Resume / Approve Travel Plan (HITL)
* **Endpoint**: `POST /api/travel/resume`
* **Content-Type**: `application/json`
* **Request Body**:
  ```json
  {
    "thread_id": "user_e23a91bc74d84f1a",
    "approved": true,
    "feedback": "Optional revision notes or preferences"
  }
  ```
* **Response**:
  ```json
  {
    "success": true,
    "thread_id": "user_e23a91bc74d84f1a",
    "answer": "# Final Polished Tokyo Guide...",
    "requires_approval": false,
    "approved": true,
    "final_response": "..."
  }
  ```

### 2. Retrieve Saved Session
* **Endpoint**: `GET /api/travel/session/{thread_id}`
* **Response**:
  ```json
  {
    "success": true,
    "thread_id": "user_e23a91bc74d84f1a",
    "user_query": "Plan a 5-day trip to Tokyo from New Delhi in October",
    "answer": "# Tokyo Itinerary...",
    "flight_results": "...",
    "hotel_results": "...",
    "itinerary": "...",
    "llm_calls": 4
  }
  ```

### 3. Health Check
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