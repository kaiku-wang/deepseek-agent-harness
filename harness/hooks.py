"""Lifecycle hooks and host-controlled tool permission policy."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable


EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
DENIED_COMMANDS = ("rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=")


class Hooks:
    def __init__(self):
        self.callbacks: dict[str, list[Callable]] = defaultdict(list)

    def register(self, event: str, callback: Callable) -> None:
        if event not in EVENTS:
            raise ValueError(f"未知 Hook 事件：{event}")
        self.callbacks[event].append(callback)

    def trigger(self, event: str, *args):
        if event not in EVENTS:
            raise ValueError(f"未知 Hook 事件：{event}")
        for callback in self.callbacks[event]:
            result = callback(*args)
            if result is not None:
                return result
        return None


class PermissionPolicy:
    def __init__(self, approval: Callable[[str, str], bool] | None = None,
                 mcp_policy: Callable[[str], str] | None = None):
        self.approval = approval
        self.mcp_policy = mcp_policy or (lambda _: "confirm")

    def check(self, name: str, args: dict) -> str | None:
        if name == "bash":
            command = args.get("command", "")
            if not isinstance(command, str):
                return "Permission denied: shell command must be a string"
            if any(pattern in command.lower() for pattern in DENIED_COMMANDS):
                return "Permission denied: command matches the deny list"
            if threading.current_thread() is not threading.main_thread():
                return "Permission denied: background turn cannot ask for shell approval"
            if not self.approval or not self.approval("bash", command):
                return "Permission denied: shell command was not approved"
        if name.startswith("mcp__") and self.mcp_policy(name) != "allow":
            if threading.current_thread() is not threading.main_thread():
                return "Permission denied: background turn cannot ask for MCP approval"
            if not self.approval or not self.approval("mcp", name):
                return "Permission denied: MCP tool was not approved"
        if name == "spawn_teammate":
            if threading.current_thread() is not threading.main_thread():
                return "Permission denied: background turn cannot approve a teammate"
            if not self.approval or not self.approval("teammate", str(args.get("name", ""))):
                return "Permission denied: teammate was not approved"
        if name == "remove_worktree" and args.get("discard_changes") is True:
            if threading.current_thread() is not threading.main_thread():
                return "Permission denied: background turn cannot approve discarding changes"
            if not self.approval or not self.approval("discard_worktree", str(args.get("name", ""))):
                return "Permission denied: discarding worktree changes was not approved"
        return None
