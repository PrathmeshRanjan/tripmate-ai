# Voyagent AI: Multi-Agent Travel Planner

Live Deployment: [https://tripmate-ai-546l.onrender.com/](https://tripmate-ai-546l.onrender.com/)

---

## Overview

Voyagent AI is an autonomous, multi-agent travel planning system built with LangGraph, Model Context Protocol (MCP), FastAPI, and PostgreSQL. It transforms natural language travel requests into structured itineraries by coordinating specialized AI agents. Each agent handles a distinct stage of travel planning—including flight route discovery, accommodation research, local weather analysis, activity scheduling, and synthesis—while persisting state and conversation checkpoints to a PostgreSQL database.

---

## System Architecture

The application implements a directed acyclic graph workflow where state flows sequentially through specialized nodes. Each node queries standardized Model Context Protocol (MCP) servers, updates the shared graph state, and passes context to downstream agents.

```mermaid
flowchart TD
    User([User Request]) --> API[FastAPI Endpoint: /api/travel]
    API --> Checkpointer[PostgreSQL Checkpointer: PostgresSaver]
    Checkpointer --> FlightAgent[Flight Agent]
    
    subgraph AgentPipeline [LangGraph Multi-Agent Workflow]
        FlightAgent -->|Flight Routes & Schedules| HotelAgent[Hotel Agent]
        HotelAgent -->|Accommodations & Pricing| WeatherAgent[Weather Agent]
        WeatherAgent -->|Live Weather & 5-Day Forecast| ItineraryAgent[Itinerary Agent]
        ItineraryAgent -->|Daily Activities & Logistics| FinalAgent[Final Synthesizer Agent]
    end
    
    subgraph MCPClient [MultiServerMCPClient Architecture]
        FlightAgent -.->|stdio transport| MCP_Aviation[AviationStack MCP Server]
        HotelAgent -.->|streamable_http transport| MCP_Tavily[Tavily Remote MCP Server]
        WeatherAgent -.->|stdio transport| MCP_Weather[Custom Weather FastMCP Server]
    end
    
    MCP_Aviation -.->|Flight Data| AviationAPI[AviationStack API]
    MCP_Tavily -.->|Search Data| TavilyAPI[Tavily Search API]
    MCP_Weather -.->|Weather & Forecast| OpenWeatherAPI[OpenWeatherMap API]
    
    FinalAgent --> StateSave[(PostgreSQL Checkpoint Storage)]
    StateSave --> Response[JSON Response / Markdown Report]
    Response --> UI[Web Interface & PDF Generator]
```

---

## Specialized Agents

### 1. Flight Agent (`flight_agent`)
* **Role**: Extracts origin and destination 3-letter IATA codes and the destination city in a single entity-extraction step.
* **Tool Integration**: Queries the AviationStack MCP server (`list_routes` and `flight_arrival_departure_schedule` via stdio transport) to fetch route connections and airport schedules.
* **Output**: Extracts route options, airline recommendations, expected durations, and airfare guidance.

### 2. Hotel Agent (`hotel_agent`)
* **Role**: Evaluates accommodation options matching the user's destination, budget preferences, and group size.
* **Tool Integration**: Queries the Tavily Remote MCP server (`streamable_http` transport) to gather real-time hotel ratings, neighborhood safety profiles, amenities, and price tiers.
* **Output**: Curates a list of recommended stays categorized across budget, mid-tier, and premium brackets.

### 3. Weather Agent (`weather_agent`)
* **Role**: Retrieves real-time weather metrics and upcoming 5-day forecasts for the destination city.
* **Tool Integration**: Calls the custom Weather FastMCP server (`weather_custom_mcp_server.py`) over stdio to query OpenWeatherMap endpoints (`get_current_weather` and `get_forecast`).
* **Output**: Provides current temperature, perceived temperature, humidity, sky condition, wind speed, and multi-day forecast checkpoints.

### 4. Itinerary Agent (`itinerary_agent`)
* **Role**: Builds an organized, day-by-day itinerary balancing travel pace, geographically grouped attractions, transit times, weather conditions, and meal options.
* **Context**: Consumes flight timings, hotel base locations, and weather conditions established by preceding agents.
* **Output**: Generates a detailed schedule with morning, afternoon, and evening breakdowns.

### 5. Final Synthesizer Agent (`final_agent`)
* **Role**: Consolidates all intermediate findings into a cohesive Markdown travel report.
* **Content**: Includes trip summaries, flight guides, hotel suggestions, weather briefings, day-by-day schedules, estimated budgets, and packing/transit tips.

---

## State Management and Persistence

The multi-agent graph operates on a shared typed dictionary (`TravelState`) containing:

```python
class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
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
git clone https://github.com/PrathmeshRanjan/tripmate-ai.git
cd tripmate-ai
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
    "answer": "# Tokyo Itinerary...",
    "flight_results": "...",
    "hotel_results": "...",
    "itinerary": "...",
    "llm_calls": 4
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