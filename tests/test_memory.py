import json
from pathlib import Path

from harness.memory import MemoryStore
from harness.provider import ModelReply


def _reply(content):
    return ModelReply(content, None, [], "stop", "fake", {})


def test_structured_memory_extracts_only_durable_unique_nonsecret_records(tmp_path: Path):
    class Provider:
        def complete(self, messages, tools, *, max_tokens=None):
            return _reply(json.dumps([
                {"name": "Stack", "type": "project", "scope": "persistent",
                 "description": "项目技术栈", "body": "项目使用 DeepSeek"},
                {"name": "Temporary", "type": "project", "scope": "current_task",
                 "description": "本次任务", "body": "临时说明"},
                {"name": "Secret", "type": "project", "scope": "persistent",
                 "description": "凭据", "body": "API_KEY=secret-value"},
                {"name": "Stack", "type": "project", "scope": "persistent",
                 "description": "项目技术栈", "body": "项目使用 DeepSeek"},
            ], ensure_ascii=False))

    memory = MemoryStore(tmp_path)
    messages = [{"role": "user", "content": "项目是什么？"},
                {"role": "assistant", "content": "项目使用 DeepSeek"}]
    assert memory.extract_after_turn(Provider(), messages) == 1
    assert "项目使用 DeepSeek" in memory.recall("项目技术栈")
    assert "Stack" in memory.read_index()
    assert len(memory.records()) == 1
    assert "secret-value" not in memory.read_file("stack.md")
    assert memory.read_file("../stack.md") is None


def test_model_selection_and_keyword_fallback(tmp_path: Path):
    memory = MemoryStore(tmp_path)
    memory.write_record({"name": "DeepSeek", "type": "project",
                         "description": "模型提供商", "body": "API 使用 DeepSeek"})
    memory.write_record({"name": "Git", "type": "project",
                         "description": "版本管理", "body": "使用 Git"})
    messages = [{"role": "user", "content": "DeepSeek 模型提供商是什么？"}]

    class Selector:
        def complete(self, messages, tools, *, max_tokens=None):
            return _reply("selected: [0, 0, 999]")

    selected = json.loads(memory.load_memories(Selector(), messages))
    assert len(selected) == 1 and selected[0]["source"] == "deepseek.md"

    class FailingSelector:
        def complete(self, messages, tools, *, max_tokens=None):
            raise RuntimeError("offline")

    fallback = json.loads(memory.load_memories(FailingSelector(), messages))
    assert fallback[0]["source"] == "deepseek.md"


def test_consolidation_and_legacy_migration(tmp_path: Path):
    legacy = tmp_path / ".harness" / "memory.jsonl"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"text": "旧版项目事实"}, ensure_ascii=False) + "\n", encoding="utf-8")
    memory = MemoryStore(tmp_path)
    assert "旧版项目事实" in memory.read_index()
    MemoryStore(tmp_path)
    assert len(memory.records()) == 1
    for index in range(9):
        memory.write_record({"name": f"Fact {index}", "type": "project",
                             "description": f"项目事实 {index}", "body": f"稳定事实 {index}"})

    class Consolidator:
        def complete(self, messages, tools, *, max_tokens=None):
            return _reply(json.dumps([
                {"name": "Merged", "type": "project",
                 "description": "合并后事实", "body": "稳定项目事实"}]))

    assert memory.consolidate(Consolidator()) == 1
    assert [record["name"] for record in memory.records()] == ["Merged"]
    assert "Merged" in memory.read_index()
    assert [record["name"] for record in MemoryStore(tmp_path).records()] == ["Merged"]
