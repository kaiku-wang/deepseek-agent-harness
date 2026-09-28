"""Late-bound in-process MCP stand-ins from the original course harness.

These model tools/list and tools/call. They are deliberately labelled mock
servers and do not claim a network or stdio MCP connection.
"""

from __future__ import annotations

import re
from typing import Callable

from .tools import Tool, ToolRegistry


class MockMCPServer:
    def __init__(self, name: str, definitions: list[dict], handlers: dict[str, Callable]):
        names = [item.get("name") for item in definitions]
        if not all(isinstance(name, str) and name for name in names):
            raise ValueError("每个 MCP 工具需要非空名称")
        if len(names) != len(set(names)) or set(names) != set(handlers):
            raise ValueError("MCP 工具定义与处理器不一致")
        self.name = name
        self.definitions = definitions
        self.handlers = handlers

    def list_tools(self) -> list[dict]:
        return list(self.definitions)

    def call_tool(self, name: str, args: dict) -> str:
        if name not in self.handlers:
            return f"MCP error: unknown tool '{name}'"
        try:
            return str(self.handlers[name](**args))
        except Exception as exc:
            return f"MCP error: {type(exc).__name__}: {exc}"


def docs_server() -> MockMCPServer:
    return MockMCPServer("docs", [
        {"name": "search", "description": "Search the documentation.",
         "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}},
                         "required": ["query"]}, "annotations": {"readOnlyHint": True}},
        {"name": "get_version", "description": "Get the documentation API version.",
         "inputSchema": {"type": "object", "properties": {}},
         "annotations": {"readOnlyHint": True}},
    ], {"search": lambda query: f"[docs] Found 3 results for '{query}'",
        "get_version": lambda: "[docs] API v2.1.0"})


def deploy_server() -> MockMCPServer:
    return MockMCPServer("deploy", [
        {"name": "trigger", "description": "Trigger a deployment.",
         "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}},
                         "required": ["service"]}, "annotations": {"destructiveHint": True}},
        {"name": "status", "description": "Check deployment status.",
         "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}},
                         "required": ["service"]}, "annotations": {"readOnlyHint": True}},
    ], {"trigger": lambda service: f"[deploy] Triggered: {service}",
        "status": lambda service: f"[deploy] {service}: running (v1.4.2)"})


MOCK_SERVERS = {"docs": docs_server, "deploy": deploy_server}
HOST_POLICY = {("docs", "search"): "allow", ("docs", "get_version"): "allow",
               ("deploy", "status"): "allow", ("deploy", "trigger"): "confirm"}


class MCPManager:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.connected: dict[str, MockMCPServer] = {}
        self.policies: dict[str, str] = {}

    def connect(self, name: str) -> str:
        if name in self.connected:
            return f"MCP server '{name}' already connected"
        if name not in MOCK_SERVERS:
            return f"Unknown server '{name}'. Available: {', '.join(MOCK_SERVERS)}"
        server = MOCK_SERVERS[name]()
        pending = []
        for definition in server.list_tools():
            safe_server = re.sub(r"[^A-Za-z0-9_-]", "_", name)
            safe_tool = re.sub(r"[^A-Za-z0-9_-]", "_", definition["name"])
            full_name = f"mcp__{safe_server}__{safe_tool}"
            if len(full_name) > 64 or full_name in self.registry._tools:
                raise ValueError(f"MCP 工具名冲突或过长：{full_name}")
            schema = definition["inputSchema"]
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise ValueError("无效的 MCP 输入 schema")
            pending.append((full_name, definition, schema))
        for full_name, definition, schema in pending:
            tool_name = definition["name"]
            self.registry.add(Tool(full_name, definition["description"], schema,
                                   lambda _name=tool_name, _server=server, **kwargs:
                                   _server.call_tool(_name, kwargs)))
            self.policies[full_name] = HOST_POLICY.get((name, tool_name), "confirm")
        self.connected[name] = server
        names = ", ".join(item["name"] for item in server.list_tools())
        return f"Connected to MCP server '{name}'. Discovered {len(pending)} tools: {names}"

    def policy(self, tool_name: str) -> str:
        return self.policies.get(tool_name, "confirm")
