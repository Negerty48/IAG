# notebooks/Desarrollo/Agentes/mcp/math_server.py
import sys
from mcp.server.fastmcp import FastMCP

# Create a FastMCP server named "MathServer"
mcp = FastMCP("MathServer")

@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers.
    
    Args:
        a: First number.
        b: Second number.
    """
    return a + b

@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers.
    
    Args:
        a: First number.
        b: Second number.
    """
    return a * b

@mcp.tool()
def get_system_info() -> str:
    """Get basic information about the server host system.
    
    Returns:
        A string describing the Python version and platform.
    """
    import platform
    return f"Platform: {platform.platform()}, Python: {platform.python_version()}"

if __name__ == "__main__":
    # If standard execution, run the stdio transport (ideal for command line / subprocess usage)
    # FastMCP defaults to running the server over stdio when called this way.
    mcp.run(transport="streamable_http")
