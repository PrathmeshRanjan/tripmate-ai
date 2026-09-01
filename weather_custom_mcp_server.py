"""
Weather Custom MCP Server
=========================
A custom Model Context Protocol (MCP) server built using FastMCP.
Exposes real-time weather information and multi-day forecasts as standardized
MCP tools that can be consumed by LangChain/LangGraph agents or MCP clients.
"""

import os
import requests
from mcp.server.fastmcp import FastMCP

# Initialize the FastMCP server instance with a descriptive service name
mcp = FastMCP("Weather MCP Server")

# Retrieve the OpenWeatherMap API key (injected by parent process environment)
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")


@mcp.tool()
def get_current_weather(city: str) -> dict:
    """
    Retrieve real-time current weather metrics for a specified city.

    Args:
        city: Name of the city (e.g., 'Tokyo', 'London', 'New Delhi').

    Returns:
        A dictionary containing temperature, perceived temperature (feels like),
        humidity percentage, weather description, and wind speed.
    """
    # Query OpenWeatherMap Current Weather Data endpoint in metric units (Celsius)
    response = requests.get(
        "https://api.openweathermap.org/data/2.5/weather",
        params={
            "q": city,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric"
        }
    )

    data = response.json()

    # If the API returned an error (e.g., invalid city or unauthorized key), return raw payload
    if response.status_code != 200:
        return data

    # Extract and structure only the relevant weather indicators
    return {
        "city": data["name"],
        "temperature_c": data["main"]["temp"],
        "feels_like_c": data["main"]["feels_like"],
        "humidity": data["main"]["humidity"],
        "condition": data["weather"][0]["description"],
        "wind_speed": data["wind"]["speed"]
    }


@mcp.tool()
def get_forecast(city: str) -> dict:
    """
    Retrieve upcoming weather forecast entries in 3-hour increments for a city.

    Args:
        city: Name of the city (e.g., 'Paris', 'New York').

    Returns:
        A dictionary containing the target city and a list of upcoming
        forecast checkpoints with timestamps, temperatures, and conditions.
    """
    url = "https://api.openweathermap.org/data/2.5/forecast"

    params = {
        "q": city,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric"
    }

    # Query OpenWeatherMap 5-day / 3-hour forecast endpoint
    response = requests.get(url, params=params)
    data = response.json()

    # If the API returned an error status, return the raw response error
    if response.status_code != 200:
        return data

    forecast = []

    # OpenWeatherMap returns data in 3-hour intervals; take the next 5 intervals (~15 hours)
    for item in data.get("list", [])[:5]:
        forecast.append(
            {
                "datetime": item["dt_txt"],
                "temperature": item["main"]["temp"],
                "weather": item["weather"][0]["description"]
            }
        )

    return {
        "city": city,
        "forecast": forecast
    }


# Standard entrypoint to run the MCP server over stdio transport
if __name__ == "__main__":
    # mcp.run() listens for MCP client messages on standard input/output (stdio)
    mcp.run()