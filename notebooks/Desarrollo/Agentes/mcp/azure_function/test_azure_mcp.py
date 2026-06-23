# test_azure_mcp.py
import asyncio
import traceback
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async def main():
    url = "https://atr-mcp-server-cnbpfqgmemckdwdb.swedencentral-01.azurewebsites.net/mcp"
    print(f"Connecting to remote MCP server at: {url}...")
    try:
        async with streamablehttp_client(url) as (read_stream, write_stream, get_session_id):
            async with ClientSession(read_stream, write_stream) as session:
                print("Session created. Initializing...")
                await session.initialize()
                print("Session initialized successfully!")
                
                print("Listing tools...")
                tools = await session.list_tools()
                print("Available Tools:")
                for tool in tools.tools:
                    print(f"- {tool.name}: {tool.description}")
                    
                print("Calling 'list_tasks'...")
                res = await session.call_tool("list_tasks", {})
                print("Response:")
                print(res.content[0].text)
    except Exception as e:
        print(f"Error occurred: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
