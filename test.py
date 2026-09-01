import os

from langchain_mcp_adapters.client import MultiServerMCPClient

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

client = MultiServerMCPClient(
    {
       "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"
        }
    }
)