# TripMate AI: Multi-Agent Travel Planner

Live Deployment: [https://tripmate-ai-546l.onrender.com/](https://tripmate-ai-546l.onrender.com/)

---

## Overview

TripMate AI is an autonomous, multi-agent travel planning system built on top of LangGraph, FastAPI, and PostgreSQL. It transforms natural language travel requests into structured itineraries by coordinating specialized AI agents. Each agent handles a distinct stage of travel planning—including flight route discovery, accommodation research, activity scheduling, and synthesis—while persisting state and conversation checkpoints to a PostgreSQL database.

---

## System Architecture

The application implements a directed graph workflow where state flows sequentially through specialized nodes. Each node executes domain-specific prompts, queries external APIs, updates the shared graph state, and passes context to downstream agents.

```mermaid
flowchart TD
    User([User Request]) --> API[FastAPI Endpoint: /api/travel]
    API --> Checkpointer[PostgreSQL Checkpointer: PostgresSaver]
    Checkpointer --> FlightAgent[Flight Agent]
    
    subgraph AgentPipeline [LangGraph Multi-Agent Workflow]
        FlightAgent -->|Flight Schedules & Status| HotelAgent[Hotel Agent]
        HotelAgent -->|Accommodations & Pricing| ItineraryAgent[Itinerary Agent]
        ItineraryAgent -->|Daily Activities & Logistics| FinalAgent[Final Synthesizer Agent]
    end
    
    FlightAgent -.->|API Call| AviationStack[AviationStack API / Airport Resolver]
    HotelAgent -.->|Search Query| Tavily[Tavily Search API]
    
    FinalAgent --> StateSave[(PostgreSQL Checkpoint Storage)]
    StateSave --> Response[JSON Response / Markdown Report]
    Response --> UI[Web Interface & PDF Generator]
```

---

## Specialized Agents

### 1. Flight Agent (`flight_agent`)
* **Role**: Resolves origin and destination locations to valid 3-letter IATA airport codes using deterministic lookup databases (`airportsdata`, `pycountry`).
* **Tool Integration**: Queries the AviationStack API to retrieve live flight statuses, airline details, terminal information, and schedule timetables.
* **Output**: Extracts route options, transit notes, and operational flight data.

### 2. Hotel Agent (`hotel_agent`)
* **Role**: Evaluates accommodation options matching the user's destination, budget preferences, and group size.
* **Tool Integration**: Uses the Tavily Search API to gather real-time hotel ratings, neighborhood safety profiles, amenities, and price tiers.
* **Output**: Curates a list of recommended stays categorized across budget, mid-tier, and premium brackets.

### 3. Itinerary Agent (`itinerary_agent`)
* **Role**: Builds an organized, day-by-day itinerary balancing travel pace, geographically grouped attractions, transit times, and meal options.
* **Context**: Consumes the flight arrival/departure timings and hotel base locations established by preceding agents.
* **Output**: Generates a detailed schedule with morning, afternoon, and evening breakdowns.

### 4. Final Synthesizer Agent (`final_agent`)
* **Role**: Consolidates all intermediate findings into a cohesive, formatted Markdown travel report.
* **Content**: Includes budget summaries, local transit guidelines, packing recommendations, important travel advisories, and emergency contact guidance.

---

## State Management and Persistence

The multi-agent graph operates on a shared typed dictionary (`TravelState`) containing:

```python
class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
    flight_results: str
    hotel_results: str
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

### Backend
* **Python 3.11+**: Core runtime environment.
* **FastAPI**: Asynchronous web framework exposing REST endpoints and serving static assets.
* **Uvicorn**: ASGI web server implementation.
* **LangGraph & LangChain Core**: Multi-agent state graph orchestration, node routing, and message reducers.
* **Google Generative AI (Gemini 2.5 Flash)**: Primary language model for entity extraction, reasoning, and synthesis.
* **Mistral AI**: Fallback language model provider.
* **Psycopg 3 & Psycopg Pool**: PostgreSQL database adapter supporting connection pooling and binary serialization.
* **PostgreSQL / Neon**: Serverless relational database for persistent checkpoint storage.

### External APIs & Data
* **AviationStack API**: Real-time flight status, route schedules, and airline data.
* **Tavily Search API**: Search engine optimized for LLMs to retrieve live hotel and travel information.
* **airportsdata & pycountry**: Deterministic datasets mapping cities and countries to IATA airport codes.

### Frontend
* **HTML5 & Modern CSS**: Glassmorphic dark interface with responsive layouts and CSS custom properties.
* **Vanilla JavaScript (ES6+)**: Client-side state controller, asynchronous request lifecycle management, and dynamic DOM rendering.
* **Marked.js**: Client-side Markdown parser for rendering structured itineraries.
* **html2pdf.js**: Client-side PDF generation engine with print formatting.

### Infrastructure & Containerization
* **Docker**: Containerized deployment packaging application dependencies.
* **Render**: Cloud hosting platform running the containerized service.

---

## Key Features

* **Multi-Agent Pipeline**: Specialized agents independently analyze flights, hotels, and schedules before synthesizing the complete plan.
* **Real-Time Data Integration**: Direct access to real-time flight schedules and current accommodation data.
* **Deterministic Location Resolution**: Built-in resolution logic mapping natural language city and country names to standard IATA codes.
* **Full Session Continuity**: Context persists across browser refreshes and subsequent follow-up questions within the same thread.
* **Trip History Drawer**: Interactive panel allowing users to browse, reload, or delete previously generated itineraries.
* **Live Pipeline Tracker**: Visual progress indicator highlighting the active agent stage during workflow execution.
* **Markdown & PDF Export**: Instant clipboard copy and one-click PDF report download formatted for printing.
* **Robust Error Handling**: Structured fallback responses for API rate limits and network anomalies.

---

## Repository Structure

```text
TripMate/
├── app.py                  # FastAPI application, routes, and exception handlers
├── backend.py              # LangGraph graph definition, state schema, and agents
├── mcp_client.py           # Multi-server MCP client (Tavily HTTP + AviationStack stdio)
├── Dockerfile              # Container image build definition
├── .dockerignore           # Excluded patterns for Docker build context
├── pyproject.toml          # Project metadata and package dependencies
├── requirements.txt        # Locked dependency list
├── .env.example            # Template for environment configuration
├── templates/
│   └── index.html          # Jinja2 HTML layout and structural components
└── static/
    ├── style.css           # Design system, layout, and print styles
    └── script.js           # Client-side controller and session logic
```

---

## Installation and Local Setup

### Prerequisites
* Python 3.11 or higher
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

# Search and Flight Tools
TAVILY_API_KEY=your_tavily_api_key_here
AVIATIONSTACK_API_KEY=your_aviationstack_api_key_here
DEFAULT_ORIGIN_IATA=DEL

# Persistence Database
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require

# Optional LangSmith Tracing
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=tripmate-ai
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
docker build -t tripmate-ai .
```

### 2. Run the Container
```bash
docker run -d -p 8000:8000 --env-file .env --name tripmate-app tripmate-ai
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