from pathlib import Path
from types import SimpleNamespace

import httpx
from openai import APIStatusError

from harness.config import Settings
from harness.provider import DeepSeekProvider


def test_tool_call_and_reasoning_round_trip(tmp_path: Path):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content="", reasoning_content="先读取文件。",
                        tool_calls=[SimpleNamespace(id="call_1", function=SimpleNamespace(
                            name="read_file", arguments='{"path":"README.md"}'))],
                    ),
                )],
                model="deepseek-flash",
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            )

    settings = Settings(workspace=tmp_path, api_key="test")
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    provider = DeepSeekProvider(settings, client=client)
    reply = provider.complete([{"role": "user", "content": "读文件"}], [
        {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    ])
    assert reply.as_message()["reasoning_content"] == "先读取文件。"
    assert reply.as_message()["tool_calls"][0]["id"] == "call_1"
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[0]["model"] == "deepseek-flash"


def test_overload_switches_to_fallback_model(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("harness.provider.time.sleep", lambda _: None)
    models = []

    class Completions:
        def create(self, **kwargs):
            models.append(kwargs["model"])
            if len(models) == 1:
                request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
                raise APIStatusError("overloaded", response=httpx.Response(529, request=request), body=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
                    content="ok", reasoning_content=None, tool_calls=None))],
                model=kwargs["model"], usage=None)

    settings = Settings(workspace=tmp_path, api_key="test", fallback_model="deepseek-v4-pro")
    provider = DeepSeekProvider(settings, SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    assert provider.complete([{"role": "user", "content": "hi"}], []).content == "ok"
    assert models == ["deepseek-flash", "deepseek-v4-pro"]
