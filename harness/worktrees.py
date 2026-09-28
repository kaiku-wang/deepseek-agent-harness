"""Git worktree management with validated names and clean-removal checks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


class WorktreeManager:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directory = self.root / ".worktrees"

    def _git(self, *args: str) -> str:
        process = subprocess.run(["git", *args], cwd=self.root, text=True,
                                 capture_output=True, timeout=30)
        if process.returncode:
            raise ValueError(process.stderr.strip() or process.stdout.strip())
        return process.stdout.strip()

    def create(self, name: str, branch: str = "") -> str:
        if not NAME.fullmatch(name) or name in {".", ".."} or ".." in name:
            raise ValueError("工作树名称无效")
        if Path(self._git("rev-parse", "--show-toplevel")).resolve() != self.root:
            raise ValueError("工作目录必须是 Git 仓库根目录")
        path = self.directory / name
        if path.exists():
            raise ValueError("工作树已存在")
        self.directory.mkdir(exist_ok=True)
        branch = branch or f"agent/{name}"
        self._git("worktree", "add", "-b", branch, str(path), "HEAD")
        return f"已创建工作树 {path}，分支 {branch}"

    def resolve(self, name: str) -> Path:
        if not NAME.fullmatch(name) or name in {".", ".."} or ".." in name:
            raise ValueError("工作树名称无效")
        path = (self.directory / name).resolve()
        if not path.is_relative_to(self.directory.resolve()) or not path.is_dir():
            raise ValueError("工作树不存在或超出目录")
        entries = {}
        current = {}
        for line in self.list().splitlines() + [""]:
            if not line:
                if "worktree" in current:
                    entries[Path(current["worktree"]).resolve()] = current
                current = {}
            else:
                key, _, value = line.partition(" ")
                current[key] = value
        if path not in entries or entries[path].get("branch") != f"refs/heads/wt/{name}":
            raise ValueError("工作树未注册到预期 Git 分支")
        return path

    def create_for_task(self, name: str, task_id: str, tasks) -> str:
        import json
        with tasks.lock:
            task = json.loads(tasks.get(task_id))
            if task["status"] != "pending" or task["owner"] or task["worktree"]:
                raise ValueError("任务无法绑定工作树")
            result = self.create(name, f"wt/{name}")
            try:
                tasks.bind_worktree(task_id, name)
            except Exception as exc:
                raise RuntimeError(f"工作树已创建但任务绑定失败，请手动检查：{exc}") from exc
            return f"{result}；已绑定 {task_id}"

    def remove_for_task(self, name: str, tasks, discard_changes: bool = False) -> str:
        import json
        with tasks.lock:
            bound = [task for task in json.loads(tasks.list()) if task["worktree"] == name]
            if not bound or any(task["status"] != "completed" for task in bound):
                raise ValueError("工作树须绑定已完成的任务")
            result = self.remove(name, discard_changes)
            tasks.unbind_worktree(name)
            return result

    def list(self) -> str:
        return self._git("worktree", "list", "--porcelain")

    def remove(self, name: str, discard_changes: bool = False) -> str:
        if not NAME.fullmatch(name) or name in {".", ".."} or ".." in name:
            raise ValueError("工作树名称无效")
        path = self.resolve(name)
        status = subprocess.run(["git", "status", "--porcelain", "--ignored"], cwd=path,
                                text=True, capture_output=True, timeout=30)
        if status.returncode:
            raise ValueError("无法检查工作树状态")
        if status.stdout.strip() and not discard_changes:
            raise ValueError("工作树有未提交改动，拒绝移除")
        args = ("worktree", "remove", "--force", str(path)) if discard_changes else (
            "worktree", "remove", str(path))
        self._git(*args)
        return f"已移除 {path}"
