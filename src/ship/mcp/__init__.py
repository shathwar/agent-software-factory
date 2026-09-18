"""Ship MCP Server package."""

from .server import run_stdio_server, main
from .schemas import TOOLS_MANIFEST
from .tools import dispatch_tool

__all__ = [
    "run_stdio_server",
    "main",
    "TOOLS_MANIFEST",
    "dispatch_tool",
]
