# notebooks/Desarrollo/Agentes/mcp/client.py
import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run_client():
    # Define parameters to start the math_server.py server as a subprocess
    # We point to the local math_server.py file in the same directory.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_script = os.path.join(script_dir, "math_server.py")
    
    # We configure standard input/output (stdio) transport parameters.
    # We run 'python math_server.py' using the active virtual environment's Python if possible,
    # or the default python.
    python_executable = sys.executable if sys.executable else "python"
    
    server_params = StdioServerParameters(
        command=python_executable,
        args=[server_script],
        env=None
    )
    
    print(f"Connecting to MCP server using command: {python_executable} {server_script} ...")
    
    # Connect to the server using the stdio transport client
    async with stdio_client(server_params) as (read_stream, write_stream):
        # Create a ClientSession to communicate with the server
        async with ClientSession(read_stream, write_stream) as session:
            # Step 1: Initialize connection
            print("Initializing session...")
            await session.initialize()
            print("Connection established successfully!")
            
            # Step 2: List the available tools on the server
            print("\nRequesting tool list from server...")
            tools_response = await session.list_tools()
            print("Available Tools:")
            for tool in tools_response.tools:
                print(f"- Name: {tool.name}")
                print(f"  Description: {tool.description}")
                print(f"  Input Schema: {tool.inputSchema}")
            
            # Step 3: Call the 'add' tool
            val_a, val_b = 10.5, 4.25
            print(f"\nCalling 'add' tool with parameters a={val_a}, b={val_b} ...")
            add_result = await session.call_tool("add", {"a": val_a, "b": val_b})
            # Retrieve text result from response content
            result_text = add_result.content[0].text
            print(f"Result from server: {result_text}")
            
            # Step 4: Call the 'multiply' tool
            val_x, val_y = 6.0, 7.5
            print(f"\nCalling 'multiply' tool with parameters a={val_x}, b={val_y} ...")
            mult_result = await session.call_tool("multiply", {"a": val_x, "b": val_y})
            result_text = mult_result.content[0].text
            print(f"Result from server: {result_text}")
            
            # Step 5: Call the 'get_system_info' tool
            print("\nCalling 'get_system_info' tool ...")
            sys_result = await session.call_tool("get_system_info", {})
            result_text = sys_result.content[0].text
            print(f"Result from server: {result_text}")

if __name__ == "__main__":
    # Run the async client
    asyncio.run(run_client())
