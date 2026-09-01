import os
from langchain_mcp_adapters.client import MultiServerMCPClient

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

client = MultiServerMCPClient(
    {
        # Remote MCP
       "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        }
    }
)

tavily_search_tool = None

async def get_tavily_search_tool():
    global tavily_search_tool
    if tavily_search_tool is not None:
        return

    tools = await client.get_tools()

    tavily_search_tool = next(
        tool
        for tool in tools
        if tool.name == "tavily_search"
    )

async def tavily_mcp_search(query: str):
    await get_tavily_search_tool()

    result = await tavily_search_tool.ainvoke({ # async invoke
        'query': query
    })

    return result