import json
from pathlib import Path

from harness.agent import Agent
from harness.config import Settings
from harness.skills import SkillCatalog


def test_skill_discovery_and_todo_validation(tmp_path: Path):
    folder = tmp_path / "skills" / "review"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nname: review\ndescription: Check code\n---\nDo a review.", encoding="utf-8")
    catalog = SkillCatalog(tmp_path)
    assert "review: Check code" in catalog.list()
    assert "Do a review" in catalog.load("review")
    agent = Agent(Settings(workspace=tmp_path, api_key="test", auto_memory=False))
    good = json.dumps({"todos": [{"content": "read source", "status": "pending"}]})
    assert agent.registry.execute("todo_write", good).startswith("已更新 1")
    assert agent.registry.execute("todo_write", '{"todos":[{"content":"bad","status":"unknown"}]}').startswith("Error:")
