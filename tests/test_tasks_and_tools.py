import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.tasks import TaskStore
from harness.tools import WorkspaceTools


def _id(serialized: str) -> str:
    return json.loads(serialized)["id"]


def test_task_dependencies_and_cycle(tmp_path: Path):
    store = TaskStore(tmp_path)
    first = _id(store.create("first"))
    second = _id(store.create("second"))
    store.add_dependencies(second, [first])
    with pytest.raises(ValueError):
        store.claim(second)
    with pytest.raises(ValueError):
        store.add_dependencies(first, [second])
    store.claim(first)
    store.complete(first)
    assert json.loads(store.claim(second))["status"] == "in_progress"


def test_workspace_boundary_and_exact_edit(tmp_path: Path):
    tools = WorkspaceTools(tmp_path)
    with pytest.raises(ValueError):
        tools.write_file("../escape.txt", "bad")
    tools.write_file("a.txt", "one two")
    tools.edit_file("a.txt", "two", "three")
    assert (tmp_path / "a.txt").read_text() == "one three"
    with pytest.raises(ValueError):
        tools.edit_file("a.txt", "missing", "x")


def test_task_store_cross_process_lock(tmp_path: Path):
    project_root = Path(__file__).resolve().parents[1]
    script = ("from pathlib import Path; from harness.tasks import TaskStore; "
              "store=TaskStore(Path(__import__('sys').argv[1])); "
              "[store.create(f'item-{i}') for i in range(10)]")
    workers = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path)],
                                cwd=project_root, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=20)
        assert worker.returncode == 0, stderr or stdout
    assert len(json.loads(TaskStore(tmp_path).list())) == 20
