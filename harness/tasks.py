"""Durable task DAG with dependency and ownership invariants."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .locking import FileRLock


@dataclass
class Task:
    id: str
    subject: str
    description: str = ""
    status: str = "pending"
    blocked_by: list[str] = field(default_factory=list)
    owner: str | None = None
    worktree: str | None = None


class TaskStore:
    def __init__(self, root: Path):
        self.path = root / ".harness" / "tasks.json"
        self.lock = FileRLock(root / ".harness" / "tasks.lock")

    def _load(self) -> dict[str, Task]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {item["id"]: Task(**item) for item in data}

    def _save(self, tasks: dict[str, Task]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps([asdict(t) for t in tasks.values()],
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def create(self, subject: str, description: str = "") -> str:
        if not subject.strip():
            raise ValueError("任务标题不能为空")
        with self.lock:
            tasks = self._load()
            task = Task(id=f"task_{uuid.uuid4().hex[:8]}", subject=subject.strip(), description=description)
            while task.id in tasks:
                task.id = f"task_{uuid.uuid4().hex[:8]}"
            tasks[task.id] = task
            self._save(tasks)
            return json.dumps(asdict(task), ensure_ascii=False)

    def list(self) -> str:
        with self.lock:
            return json.dumps([asdict(t) for t in self._load().values()], ensure_ascii=False, indent=2)

    def get(self, task_id: str) -> str:
        with self.lock:
            task = self._load().get(task_id)
            if task is None:
                raise ValueError(f"任务不存在：{task_id}")
            return json.dumps(asdict(task), ensure_ascii=False)

    def add_dependencies(self, task_id: str, addBlockedBy: list[str]) -> str:
        with self.lock:
            tasks = self._load()
            if task_id not in tasks or any(dep not in tasks for dep in addBlockedBy):
                raise ValueError("任务或依赖 ID 不存在")
            if tasks[task_id].status != "pending":
                raise ValueError("只能修改待开始任务的依赖")
            graph = {key: set(task.blocked_by) for key, task in tasks.items()}
            graph[task_id].update(addBlockedBy)
            def visit(node: str, seen: set[str]) -> bool:
                return node in seen or any(visit(dep, seen | {node}) for dep in graph[node])
            if visit(task_id, set()):
                raise ValueError("依赖关系形成了环")
            tasks[task_id].blocked_by = sorted(graph[task_id])
            self._save(tasks)
            return self.get(task_id)

    def bind_worktree(self, task_id: str, name: str) -> str:
        with self.lock:
            tasks = self._load()
            task = tasks.get(task_id)
            if task is None or task.status != "pending" or task.owner or task.worktree:
                raise ValueError("任务必须待开始、无人认领且尚未绑定工作树")
            if any(other.worktree == name for other in tasks.values()):
                raise ValueError("工作树已绑定其他任务")
            task.worktree = name
            self._save(tasks)
            return self.get(task_id)

    def unbind_worktree(self, name: str) -> None:
        with self.lock:
            tasks = self._load()
            bound = [task for task in tasks.values() if task.worktree == name]
            if not bound or any(task.status != "completed" for task in bound):
                raise ValueError("工作树未绑定已完成的任务")
            for task in bound:
                task.worktree = None
            self._save(tasks)

    def current_for(self, owner: str) -> Task | None:
        with self.lock:
            return next((task for task in self._load().values()
                         if task.owner == owner and task.status == "in_progress"), None)

    def ready(self) -> list[Task]:
        with self.lock:
            tasks = self._load()
            return [task for task in tasks.values() if task.status == "pending"
                    and all(tasks[dep].status == "completed" for dep in task.blocked_by)]

    def release_owner(self, owner: str) -> None:
        """Return an abandoned in-progress assignment to the board."""
        with self.lock:
            tasks = self._load()
            for task in tasks.values():
                if task.owner == owner and task.status == "in_progress":
                    task.owner, task.status = None, "pending"
            self._save(tasks)

    def claim(self, task_id: str, owner: str = "agent") -> str:
        with self.lock:
            tasks = self._load()
            task = tasks.get(task_id)
            if task is None or task.status != "pending":
                raise ValueError("任务不存在或已经开始")
            if any(tasks[dep].status != "completed" for dep in task.blocked_by):
                raise ValueError("依赖任务尚未完成")
            if any(t.owner == owner and t.status == "in_progress" for t in tasks.values()):
                raise ValueError(f"{owner} 已有进行中的任务")
            task.status, task.owner = "in_progress", owner
            self._save(tasks)
            return self.get(task_id)

    def complete(self, task_id: str, owner: str = "agent") -> str:
        with self.lock:
            tasks = self._load()
            task = tasks.get(task_id)
            if task is None or task.status != "in_progress" or task.owner != owner:
                raise ValueError("仅当前负责人能完成进行中的任务")
            task.status = "completed"
            self._save(tasks)
            return self.get(task_id)
