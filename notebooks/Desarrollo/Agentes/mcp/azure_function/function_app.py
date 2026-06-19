# notebooks/Desarrollo/Agentes/mcp/azure_function/function_app.py
import azure.functions as func
import logging
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_azure_function")

# 1. Initialize FastAPI Application
# This acts as our main web server which Azure Functions will run via ASGI.
fastapi_app = FastAPI(
    title="MCP Server on Azure Functions",
    description="FastAPI + FastMCP server hosted serverless on Azure Functions using HTTP SSE Transport",
    version="1.0.0"
)

# 2. Create the FastMCP server
mcp = FastMCP("AzureFunctionsMCPServer")

# In-memory storage for our demonstration tools
tasks_db = [
    {"id": 1, "task": "Learn Model Context Protocol (MCP)", "status": "In Progress"},
    {"id": 2, "task": "Create custom MCP client", "status": "Completed"},
    {"id": 3, "task": "Deploy MCP server on Azure Functions", "status": "In Progress"}
]

# 3. Define Tools on the MCP Server
@mcp.tool()
def list_tasks() -> str:
    """List all current tasks in the database.
    
    Returns:
        A text representation of the task list.
    """
    logger.info("MCP Tool 'list_tasks' called.")
    if not tasks_db:
        return "No tasks found in the database."
    
    result = "Task List:\n"
    for t in tasks_db:
        result += f"[{t['id']}] {t['task']} - Status: {t['status']}\n"
    return result

@mcp.tool()
def add_task(title: str) -> str:
    """Add a new task to the database.
    
    Args:
        title: The description/title of the task to add.
    """
    logger.info(f"MCP Tool 'add_task' called with title: {title}")
    new_id = max([t['id'] for t in tasks_db], default=0) + 1
    new_task = {"id": new_id, "task": title, "status": "Pending"}
    tasks_db.append(new_task)
    return f"Task '{title}' added successfully with ID {new_id}."

@mcp.tool()
def update_task_status(task_id: int, status: str) -> str:
    """Update the status of a specific task.
    
    Args:
        task_id: The ID of the task to update.
        status: The new status (e.g. 'Pending', 'In Progress', 'Completed').
    """
    logger.info(f"MCP Tool 'update_task_status' called for ID: {task_id} with status: {status}")
    for t in tasks_db:
        if t['id'] == task_id:
            old_status = t['status']
            t['status'] = status
            return f"Task [{task_id}] status updated from '{old_status}' to '{status}'."
    return f"Error: Task with ID {task_id} not found."

# 4. Mount FastMCP ASGI App onto the main FastAPI App
# FastMCP handles HTTP SSE transport protocols internally. Mounting .sse_app()
# creates endpoints '/mcp/sse' and '/mcp/messages' automatically.
fastapi_app.mount("/mcp", mcp.sse_app())

# Define a root endpoint for general sanity checks
@fastapi_app.get("/")
def read_root():
    return {
        "message": "MCP Server is running on Azure Functions!",
        "endpoints": {
            "mcp_sse_stream": "/mcp/sse",
            "mcp_messages": "/mcp/messages"
        }
    }

# 5. Define the Azure Function App using AsgiFunctionApp
# This binds our FastAPI application to the Azure Functions runtime.
# http_auth_level can be set to func.AuthLevel.FUNCTION or AuthLevel.ANONYMOUS
app = func.AsgiFunctionApp(app=fastapi_app, http_auth_level=func.AuthLevel.ANONYMOUS)
