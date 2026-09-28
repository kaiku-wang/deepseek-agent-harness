"""Typed tool registry with workspace-bounded file access and output limits."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .shell import run_shell


MAX_TOOL_OUTPUT = 24_000


def _limited(value: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n[已截断；总字符数 {len(value)}]"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]

    @property
    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"重复的工具名称：{tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [tool.schema for tool in self._tools.values()]

    def execute(self, name: str, arguments: str | dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: 未知工具 {name}"
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            if not isinstance(args, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            required = tool.parameters.get("required", [])
            missing = [field for field in required if field not in args]
            if missing:
                raise ValueError(f"缺少必填参数：{', '.join(missing)}")
            unexpected = set(args) - set(tool.parameters.get("properties", {}))
            if unexpected:
                raise ValueError(f"未知参数：{', '.join(sorted(unexpected))}")
            for field, value in args.items():
                schema = tool.parameters["properties"][field]
                expected = schema.get("type")
                valid = {
                    "string": lambda item: isinstance(item, str),
                    "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
                    "boolean": lambda item: isinstance(item, bool),
                    "array": lambda item: isinstance(item, list),
                }.get(expected, lambda item: True)
                if not valid(value):
                    raise ValueError(f"参数 {field} 类型错误，期望 {expected}")
                if expected == "array" and schema.get("items", {}).get("type") == "string":
                    if not all(isinstance(item, str) for item in value):
                        raise ValueError(f"参数 {field} 必须是字符串数组")
            return str(tool.handler(**args))
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"


class WorkspaceTools:
    def __init__(self, root: Path | Callable[[], Path], shell_timeout: int = 120, background=None):
        self._root = root
        self.shell_timeout = shell_timeout
        self.background = background

    @property
    def root(self) -> Path:
        value = self._root() if callable(self._root) else self._root
        return value.resolve()

    def path(self, name: str) -> Path:
        target = (self.root / name).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("路径超出工作区")
        return target

    def read_file(self, path: str, offset: int = 0, limit: int = 300) -> str:
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError("offset 或 limit 超出范围")
        lines = self.path(path).read_text(encoding="utf-8").splitlines()
        return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines[offset:offset + limit], offset))

    def write_file(self, path: str, content: str) -> str:
        target = self.path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已写入 {target.relative_to(self.root)} ({len(content)} 字符)"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self.path(path)
        content = target.read_text(encoding="utf-8")
        count = content.count(old_text)
        if not old_text or count != 1:
            raise ValueError(f"旧文本必须恰好匹配一次，实际 {count} 次")
        target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"已编辑 {target.relative_to(self.root)}"

    def glob(self, pattern: str) -> str:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError("glob 模式必须位于工作区内")
        matches = [str(p.relative_to(self.root)) for p in self.root.glob(pattern)
                   if p.resolve().is_relative_to(self.root)]
        return "\n".join(sorted(matches[:500])) or "(无匹配)"

    def bash(self, command: str, run_in_background: bool = False) -> str:
        """Explicit coding-agent shell tool. Runs in the workspace with a timeout."""
        if not command.strip():
            raise ValueError("命令为空")
        if run_in_background:
            if self.background is None:
                raise ValueError("当前运行时不支持后台任务")
            return self.background.start(command, lambda: self.bash(command, False), self.root)
        return run_shell(command, self.root, self.shell_timeout)


def _object(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


def register_workspace_tools(registry: ToolRegistry, workspace: WorkspaceTools) -> None:
    registry.add(Tool("read_file", "读取工作区内的文本文件，可指定行偏移和行数。",
                      _object({"path": {"type": "string"}, "offset": {"type": "integer"},
                               "limit": {"type": "integer"}}, ["path"]), workspace.read_file))
    registry.add(Tool("write_file", "在工作区内新建或覆盖文本文件。",
                      _object({"path": {"type": "string"}, "content": {"type": "string"}},
                              ["path", "content"]), workspace.write_file))
    registry.add(Tool("edit_file", "仅当旧文本恰好出现一次时替换。",
                      _object({"path": {"type": "string"}, "old_text": {"type": "string"},
                               "new_text": {"type": "string"}}, ["path", "old_text", "new_text"]), workspace.edit_file))
    registry.add(Tool("glob", "列出工作区内匹配 glob 模式的文件。",
                      _object({"pattern": {"type": "string"}}, ["pattern"]), workspace.glob))
    registry.add(Tool("bash", "在工作区执行 shell 命令，返回退出码和输出。",
                      _object({"command": {"type": "string"},
                               "run_in_background": {"type": "boolean"}}, ["command"]), workspace.bash))
