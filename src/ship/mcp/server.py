"""Zero-dependency stdio Model Context Protocol (MCP) server for Ship SDLC."""

import json
import sys
import traceback
from typing import Dict, Any, Optional

from .schemas import TOOLS_MANIFEST
from .tools import dispatch_tool

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ship"
SERVER_VERSION = "1.0.0"


def send_response(response: Dict[str, Any]) -> None:
    """Write a JSON-RPC response to stdout as a single line and flush."""
    line = json.dumps(response, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def send_error(req_id: Optional[Any], code: int, message: str, data: Optional[Any] = None) -> None:
    err_obj: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err_obj["data"] = data
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err_obj,
    })


def handle_request(msg: Dict[str, Any]) -> None:
    """Process an incoming JSON-RPC request or notification."""
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    # Notification handling (no id)
    if req_id is None:
        if method == "notifications/initialized":
            sys.stderr.write("[ship-mcp] Client initialized notification received\n")
            sys.stderr.flush()
        return

    # Method dispatch
    if method == "initialize":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        })
        return

    if method == "ping":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {},
        })
        return

    if method == "tools/list":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS_MANIFEST,
            },
        })
        return

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not tool_name:
            send_error(req_id, -32602, "Invalid params: 'name' is required for tools/call")
            return

        try:
            result_data = dispatch_tool(tool_name, arguments)
            if isinstance(result_data, str):
                text_content = result_data
            elif isinstance(result_data, dict) and "text" in result_data and len(result_data) <= 2:
                text_content = str(result_data.get("text", json.dumps(result_data, indent=2)))
            else:
                text_content = json.dumps(result_data, indent=2)

            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text_content,
                        }
                    ],
                    "isError": False,
                },
            })
        except Exception as e:
            sys.stderr.write(f"[ship-mcp] Error in tool '{tool_name}': {traceback.format_exc()}\n")
            sys.stderr.flush()
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Error executing {tool_name}: {str(e)}",
                        }
                    ],
                    "isError": True,
                },
            })
        return

    # Method not found
    send_error(req_id, -32601, f"Method not found: {method}")


def run_stdio_server() -> int:
    """Run the stdio event loop processing newline-delimited JSON-RPC messages."""
    sys.stderr.write(f"[ship-mcp] Starting Ship MCP server v{SERVER_VERSION} on stdio\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as exc:
            send_error(None, -32700, f"Parse error: {str(exc)}")
            continue

        handle_request(msg)

    sys.stderr.write("[ship-mcp] Stdio stream closed, exiting.\n")
    sys.stderr.flush()
    return 0


def main() -> int:
    return run_stdio_server()


if __name__ == "__main__":
    sys.exit(main())
