"""
MCP server entry point using the official MCP Python SDK.
This is fully compatible with Claude Desktop.
"""
from __future__ import annotations
import asyncio
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

from dynatrace_mcp.app import list_tools, handle_tool_call

app = Server("dynatrace-support-mcp")


@app.list_tools()
async def _list_tools() -> list[Tool]:
    raw = list_tools().get("tools", [])
    return [
        Tool(
            name=t["name"],
            description=t.get("description", ""),
            inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
        )
        for t in raw
    ]


@app.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    result = handle_tool_call(name, arguments or {})
    texts = [
        TextContent(type="text", text=item["text"])
        for item in result.get("content", [])
        if item.get("type") == "text"
    ]
    return texts or [TextContent(type="text", text="No output returned.")]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_run())
