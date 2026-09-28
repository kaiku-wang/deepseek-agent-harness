import time

from harness.background import BackgroundManager
from harness.hooks import Hooks, PermissionPolicy
from harness.mcp import MCPManager
from harness.tools import ToolRegistry


def test_mock_mcp_late_discovery_and_host_policy():
    registry = ToolRegistry()
    mcp = MCPManager(registry)
    assert not registry.schemas()
    assert mcp.connect("missing").startswith("Unknown server")
    mcp.connect("docs")
    assert mcp.connect("docs") == "MCP server 'docs' already connected"
    assert registry.execute("mcp__docs__search", '{"query":"agent"}') == "[docs] Found 3 results for 'agent'"
    assert mcp.connected["docs"].list_tools()[0]["annotations"]["readOnlyHint"] is True
    assert mcp.connected["docs"].call_tool("missing", {}) == "MCP error: unknown tool 'missing'"
    mcp.connect("deploy")
    assert mcp.connected["deploy"].list_tools()[0]["annotations"]["destructiveHint"] is True
    assert mcp.policy("mcp__docs__search") == "allow"
    assert mcp.policy("mcp__deploy__trigger") == "confirm"


def test_background_result_delivered_once():
    manager = BackgroundManager()
    started = manager.start("echo hello", lambda: "exit_code=0\nhello")
    assert "bg_0001" in started
    deadline = time.monotonic() + 2
    while not manager.has_ready() and time.monotonic() < deadline:
        time.sleep(0.01)
    notifications = manager.collect()
    assert len(notifications) == 1
    assert "<status>completed</status>" in notifications[0]
    assert manager.collect() == []


def test_hook_veto_and_mcp_confirmation():
    hooks = Hooks()
    policy = PermissionPolicy(lambda kind, _: kind == "mcp",
                              lambda _: "confirm")
    hooks.register("PreToolUse", policy.check)
    assert hooks.trigger("PreToolUse", "bash", {"command": "shutdown now"}).startswith("Permission denied")
    assert hooks.trigger("PreToolUse", "mcp__deploy__trigger", {}) is None
    assert hooks.trigger("PreToolUse", "spawn_teammate", {"name": "worker"}).startswith("Permission denied")
