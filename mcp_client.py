import os
import sys
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY', "")
AVIATION_STACK_API_KEY = os.getenv('AVIATION_STACK_API_KEY') or os.getenv('AVIATIONSTACK_API_KEY', "")

client = MultiServerMCPClient(
    {
        # Remote MCP
        "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        },
        "aviationstack": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                "-m",
                "aviationstack_mcp"
            ],
            "env": {
                "AVIATION_STACK_API_KEY": AVIATION_STACK_API_KEY
            }
        }
    }
)

# ==============================================================================
# Tavily MCP
# ==============================================================================

tavily_search_tool = None

async def get_tavily_search_tool():
    global tavily_search_tool
    if tavily_search_tool is not None:
        return tavily_search_tool

    try:
        tools = await client.get_tools(server_name='tavily')
        tavily_search_tool = next(
            (tool for tool in tools if tool.name == "tavily_search"),
            None
        )
    except Exception as e:
        print(f"Warning: Tavily MCP tool fetch failed: {e}")
        tavily_search_tool = None

    return tavily_search_tool

async def tavily_mcp_search(query: str):
    tool = await get_tavily_search_tool()
    if tool is None:
        return f"Hotel search unavailable for query: {query}"

    result = await tool.ainvoke({
        'query': query
    })

    return result

# ==============================================================================
# AviationStack MCP
# ==============================================================================

aviation_tools = {}

async def initialize_aviation_tools():
    global aviation_tools

    if aviation_tools:
        return aviation_tools

    try:
        tools = await client.get_tools(server_name='aviationstack')
        aviation_tools = {tool.name: tool for tool in tools}
    except Exception as e:
        print(f"Warning: AviationStack MCP tool discovery failed: {e}")
        aviation_tools = {}

    return aviation_tools

async def aviation_mcp_call(
    tool_name: str,
    tool_args: dict = None
):
    await initialize_aviation_tools()

    tool = aviation_tools.get(tool_name)

    if tool is None:
        available_tools = ", ".join(sorted(aviation_tools.keys()))
        raise ValueError(
            f"AviationStack tool '{tool_name}' was not found. "
            f"Available tools: {available_tools or 'none'}"
        )

    result = await tool.ainvoke(tool_args or {})
    return result