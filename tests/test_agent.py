from pathlib import Path
import time

from harness.agent import Agent
from harness.config import Settings
from harness.provider import ModelReply


class FakeProvider:
    def __init__(self):
        self.received = []

    def complete(self, messages, tools, *, max_tokens=None):
        self.received.append(messages)
        if len(self.received) == 1:
            return ModelReply("", "需要列出文件。", [{
                "id": "call_a", "type": "function", "function": {
                    "name": "glob", "arguments": '{"pattern":"*.txt"}'}}],
                "tool_calls", "deepseek-flash", {})
        return ModelReply("看到文件。", "文件已列出。", [], "stop", "deepseek-flash", {})


def test_agent_executes_tools_and_preserves_reasoning(tmp_path: Path):
    (tmp_path / "demo.txt").write_text("hello", encoding="utf-8")
    provider = FakeProvider()
    agent = Agent(Settings(workspace=tmp_path, api_key="test"), provider=provider)
    assert agent.run("有哪些 txt 文件？") == "看到文件。"
    second = provider.received[1]
    assert second[-2]["reasoning_content"] == "需要列出文件。"
    assert second[-1] == {"role": "tool", "tool_call_id": "call_a", "content": "demo.txt"}


class BackgroundProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools, *, max_tokens=None):
        self.calls += 1
        if self.calls == 1:
            return ModelReply("", "", [{"id": "bg_call", "type": "function",
                                      "function": {"name": "bash", "arguments":
                                                   '{"command":"echo hello","run_in_background":true}'}}],
                              "tool_calls", "fake", {})
        return ModelReply("后台任务已开始", "", [], "stop", "fake", {})


def test_background_bash_wakes_agent(tmp_path: Path):
    provider = BackgroundProvider()
    agent = Agent(Settings(workspace=tmp_path, api_key="test", auto_memory=False),
                  provider=provider, approval=lambda kind, detail: True)
    assert agent.run("后台执行 echo") == "后台任务已开始"
    deadline = time.monotonic() + 3
    while not agent.pending_events() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert "<task_notification>" in agent.collect_events()


def test_first_model_response_acknowledges_delivery_once(tmp_path: Path):
    provider = FakeProvider()
    agent = Agent(Settings(workspace=tmp_path, api_key="test", auto_memory=False), provider=provider)
    accepted = []
    agent.run("列文件", on_accepted=lambda: accepted.append(True))
    assert accepted == [True]


def test_length_recovery_escalates_output_budget(tmp_path: Path):
    class Provider:
        def __init__(self):
            self.budgets = []

        def complete(self, messages, tools, *, max_tokens=None):
            self.budgets.append(max_tokens)
            if len(self.budgets) == 1:
                return ModelReply("partial", None, [], "length", "fake", {})
            return ModelReply("complete", None, [], "stop", "fake", {})

    provider = Provider()
    agent = Agent(Settings(workspace=tmp_path, api_key="test", auto_memory=False), provider=provider)
    assert agent.run("回答问题") == "complete"
    assert provider.budgets == [8192, 16384]


def test_prompt_too_long_triggers_model_summary(tmp_path: Path):
    class Provider:
        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools, *, max_tokens=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("context_length_exceeded")
            if self.calls == 2:
                assert tools == []
                return ModelReply("已完成前期准备", None, [], "stop", "fake", {})
            assert "Authoritative request" in messages[-1]["content"]
            return ModelReply("恢复成功", None, [], "stop", "fake", {})

    provider = Provider()
    agent = Agent(Settings(workspace=tmp_path, api_key="test", auto_memory=False), provider=provider)
    assert agent.run("继续任务") == "恢复成功"
    assert provider.calls == 3


def test_agent_loads_selected_memory_then_extracts_new_record(tmp_path: Path):
    class Provider:
        def __init__(self):
            self.calls = []

        def complete(self, messages, tools, *, max_tokens=None):
            self.calls.append((messages, tools))
            if max_tokens == 200:
                return ModelReply("[0]", None, [], "stop", "fake", {})
            if max_tokens == 1000:
                return ModelReply('{"ignored":true}\n[{"name":"Preferred language",'
                                  '"type":"user","scope":"persistent",'
                                  '"description":"中文回复","body":"用户偏好中文回复"}]',
                                  None, [], "stop", "fake", {})
            assert "稳定项目事实" in messages[0]["content"]
            return ModelReply("已完成", None, [], "stop", "fake", {})

    provider = Provider()
    agent = Agent(Settings(workspace=tmp_path, api_key="test"), provider=provider)
    agent.memory.write_record({"name": "Project", "type": "project",
                               "description": "项目背景", "body": "稳定项目事实"})
    assert agent.run("继续项目") == "已完成"
    assert len(provider.calls) == 3
    assert "用户偏好中文回复" in agent.memory.read_file("preferred-language.md")
