from pathlib import Path

from harness.context import Conversation
from harness.provider import ModelReply


def test_compaction_keeps_tool_call_pairs(tmp_path: Path):
    conversation = Conversation(tmp_path, max_chars=1500)
    conversation.add({"role": "user", "content": "处理文件"})
    for index in range(5):
        conversation.add({"role": "assistant", "content": "", "tool_calls": [{
            "id": f"call_{index}", "type": "function", "function": {
                "name": "read_file", "arguments": "{}"}}]})
        conversation.add({"role": "tool", "tool_call_id": f"call_{index}", "content": "x" * 2000})
    conversation.compact()
    calls = [call["id"] for message in conversation.messages
             for call in message.get("tool_calls", [])]
    results = [message["tool_call_id"] for message in conversation.messages
               if message["role"] == "tool"]
    assert calls == results
    assert "已压缩" in conversation.messages[2]["content"]


def test_large_tool_result_is_saved_with_preview(tmp_path: Path):
    conversation = Conversation(tmp_path)
    preview = conversation.persist_tool_result("call_1", "x" * 31_000)
    assert "<persisted-output>" in preview
    saved = next(conversation.tool_results.glob("call_1_*.txt"))
    assert len(saved.read_text(encoding="utf-8")) == 31_000


def test_model_summary_keeps_authoritative_request(tmp_path: Path):
    class Provider:
        def complete(self, messages, tools, *, max_tokens=None):
            assert tools == []
            return ModelReply("已修改 a.py，测试通过", None, [], "stop", "fake", {})

    conversation = Conversation(tmp_path)
    conversation.add({"role": "user", "content": "修改 a.py"})
    conversation.summarize(Provider(), "继续完成用户当前任务")
    content = conversation.messages[0]["content"]
    assert "Authoritative request:\n继续完成用户当前任务" in content
    assert "已修改 a.py" in content
