"""DeepSeek Chat Completions adapter and bounded transient-error recovery."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from .config import Settings


@dataclass(frozen=True)
class ModelReply:
    content: str
    reasoning_content: str | None
    tool_calls: list[dict[str, Any]]
    finish_reason: str | None
    model: str
    usage: dict[str, int]

    def as_message(self) -> dict[str, Any]:
        """Keep DeepSeek reasoning even after a final answer when tools are supplied."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.reasoning_content is not None:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls
        return message


class DeepSeekProvider:
    def __init__(self, settings: Settings, client: OpenAI | None = None):
        self.settings = settings
        self.client = client or OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=90,
            max_retries=0,  # one retry layer, controlled below
        )

    def complete(self, messages: list[dict], tools: list[dict], *, max_tokens: int | None = None) -> ModelReply:
        model = self.settings.model
        for attempt in range(3):
            try:
                options: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens or self.settings.max_output_tokens,
                    "extra_body": {"thinking": {"type": self.settings.thinking}},
                }
                if tools:
                    options["tools"] = tools
                if self.settings.thinking == "enabled":
                    options["reasoning_effort"] = self.settings.reasoning_effort
                result = self.client.chat.completions.create(**options)
                if not result.choices:
                    raise RuntimeError("DeepSeek 返回了空 choices。")
                choice = result.choices[0]
                calls = [
                    {"id": call.id, "type": "function", "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    }}
                    for call in (choice.message.tool_calls or [])
                ]
                usage = result.usage
                return ModelReply(
                    content=choice.message.content or "",
                    reasoning_content=getattr(choice.message, "reasoning_content", None),
                    tool_calls=calls,
                    finish_reason=choice.finish_reason,
                    model=result.model,
                    usage={
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    },
                )
            except (RateLimitError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
                status = getattr(exc, "status_code", None)
                retryable = isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)) or status in {429, 500, 502, 503, 504, 529}
                if not retryable or attempt == 2:
                    raise
                if status in {503, 529} and self.settings.fallback_model:
                    model = self.settings.fallback_model
                time.sleep(min(2 ** attempt + random.random(), 8))
        raise AssertionError("unreachable")
