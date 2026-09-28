import json
import subprocess
from pathlib import Path

import pytest

from harness.tasks import TaskStore
from harness.worktrees import WorktreeManager


def _git(root: Path, *args: str):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_task_bound_worktree_lifecycle(tmp_path: Path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("demo", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "initial")
    tasks = TaskStore(tmp_path)
    task_id = json.loads(tasks.create("implement"))["id"]
    manager = WorktreeManager(tmp_path)
    manager.create_for_task("isolated", task_id, tasks)
    assert manager.resolve("isolated").is_dir()
    assert json.loads(tasks.get(task_id))["worktree"] == "isolated"
    tasks.claim(task_id)
    tasks.complete(task_id)
    dirty = manager.resolve("isolated") / "untracked.txt"
    dirty.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        manager.remove_for_task("isolated", tasks)
    dirty.unlink()
    manager.remove_for_task("isolated", tasks)
    assert json.loads(tasks.get(task_id))["worktree"] is None
