"""
Voyagent AI - FastAPI Web Server
=================================
This module acts as the HTTP interface for Voyagent. It serves the Jinja2 HTML/CSS frontend
and exposes REST API endpoints that connect frontend requests to the LangGraph multi-agent backend.
"""

from pathlib import Path
import traceback
import uvicorn

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Import the core LangGraph multi-agent travel planner execution pipeline
from backend import run_travel_agent, get_travel_session

# Locate the root directory to safely resolve static files and templates
BASE_DIR = Path(__file__).resolve().parent

# ==============================================================================
# 1. APPLICATION INITIALIZATION & CONFIGURATION
# ==============================================================================

app = FastAPI(
    title="Voyagent AI",
    description="LangGraph Multi-Agent Travel Planner with FastAPI Frontend",
    version="1.0.0"
)

# Mount static directory for CSS, JavaScript, and images
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)

# Configure Jinja2 templates directory for rendering HTML views
templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


# ==============================================================================
# 2. REQUEST DATA MODELS (PYDANTIC)
# ==============================================================================

class TravelRequest(BaseModel):
    """
    Schema for incoming trip planning requests from the frontend.
    - message: The user's travel prompt (e.g. 'Plan a 5-day trip to Tokyo from Delhi').
    - thread_id: Optional session ID used by LangGraph Postgres checkpointer for conversation memory.
    """
    message: str 
    thread_id: str | None = None


# ==============================================================================
# 3. ROUTE HANDLERS
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """
    Serves the main interactive web UI.
    Renders the index.html template from the templates directory.
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


@app.post("/api/travel")
def travel_planner(request_data: TravelRequest):
    """
    Primary API endpoint for trip planning.
    Receives user query -> Invokes LangGraph multi-agent workflow -> Returns complete itinerary & results.
    """
    try:
        user_message = request_data.message.strip()

        # Input validation: reject empty messages
        if not user_message:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Message cannot be empty."
                }
            )

        # Execute the LangGraph travel agent pipeline (Flight -> Hotel -> Weather -> Itinerary -> Final)
        result = run_travel_agent(
            user_input=user_message,
            thread_id=request_data.thread_id
        )

        # Return structured response to frontend
        return JSONResponse(
            content={
                "success": True,
                "thread_id": result["thread_id"],
                "answer": result["answer"],
                "flight_results": result["flight_results"],
                "hotel_results": result["hotel_results"],
                "weather_results": result.get("weather_results", ""),
                "itinerary": result["itinerary"],
                "llm_calls": result["llm_calls"],
            }
        )

    except Exception as e:
        # Log stack trace to server console for debugging
        print("ERROR:", e)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/api/travel/session/{thread_id}")
def get_session(thread_id: str):
    """
    Restores the latest saved travel plan state from Postgres for a given session/thread_id.
    """
    try:
        session_data = get_travel_session(thread_id)

        if not session_data or not session_data.get("answer"):
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": "Session not found or has no saved plan."
                }
            )

        return JSONResponse(
            content={
                "success": True,
                **session_data
            }
        )

    except Exception as e:
        print("ERROR restoring session:", e)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.get("/health")
async def health_check():
    """
    Health check endpoint for container health probes and uptime monitoring.
    """
    return {
        "status": "ok",
        "message": "AI Travel Planner API is running"
    }


@app.get("/favicon.ico")
async def favicon():
    """
    Handles browser favicon request to prevent 404 errors in logs.
    """
    return JSONResponse(content={})


# ==============================================================================
# 4. ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    # Start Uvicorn development server with live code reloading
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )