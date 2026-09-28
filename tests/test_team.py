import time
import json
from pathlib import Path

from harness.provider import ModelReply
from harness.tasks import TaskStore
from harness.team import TeamManager
from harness.worktrees import WorktreeManager


class PlanProvider:
    def __init__(self):
        self.count = 0

    def complete(self, messages, tools, *, max_tokens=None):
        self.count += 1
        if self.count == 1:
            return ModelReply("", "", [{"id": "plan_call", "type": "function",
                                      "function": {"name": "submit_plan",
                                                   "arguments": '{"plan":"先读再写"}'}}],
                              "tool_calls", "fake", {})
        return ModelReply("计划获批，任务完成", "", [], "stop", "fake", {})


def _wait_events(team, expected: str):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if team.has_lead_events():
            events = team.lead_events()
            for event in events:
                if event["type"] == expected:
                    return event
        time.sleep(0.02)
    raise AssertionError(f"No {expected} event")


def test_team_mailbox_plan_approval_and_shutdown(tmp_path: Path):
    provider = PlanProvider()
    team = TeamManager(tmp_path, provider, TaskStore(tmp_path), WorktreeManager(tmp_path), 5)
    team.spawn("worker", "coder", "处理任务", require_plan=True)
    request = _wait_events(team, "plan_approval_request")
    request_id = request["metadata"]["request_id"]
    assert team.teammates["worker"].gate == "pending"
    assert team.review_plan(request_id, True).startswith("计划 approved")
    result = _wait_events(team, "result")
    assert result["content"] == "计划获批，任务完成"
    team.request_shutdown("worker")
    response = _wait_events(team, "shutdown_response")
    assert response["metadata"]["approve"] is True


class PlanWriteProvider:
    def __init__(self):
        self.count = 0

    def complete(self, messages, tools, *, max_tokens=None):
        self.count += 1
        if self.count == 1:
            name, arguments = "submit_plan", '{"plan":"写 marker.txt"}'
        elif self.count == 2:
            name, arguments = "write_file", '{"path":"marker.txt","content":"done"}'
        else:
            return ModelReply("写入完成", "", [], "stop", "fake", {})
        return ModelReply("", "", [{"id": f"call_{self.count}", "type": "function",
                                    "function": {"name": name, "arguments": arguments}}],
                          "tool_calls", "fake", {})


def test_plan_gate_blocks_mutation_until_approval(tmp_path: Path):
    tasks = TaskStore(tmp_path)
    task_id = json.loads(tasks.create("write marker"))["id"]
    team = TeamManager(tmp_path, PlanWriteProvider(), tasks, WorktreeManager(tmp_path), 5)
    team.spawn("writer", "coder", "写文件", task_id=task_id, require_plan=True)
    request = _wait_events(team, "plan_approval_request")
    assert not (tmp_path / "marker.txt").exists()
    team.review_plan(request["metadata"]["request_id"], True)
    _wait_events(team, "result")
    assert (tmp_path / "marker.txt").read_text(encoding="utf-8") == "done"
    team.request_shutdown("writer")
    _wait_events(team, "shutdown_response")
