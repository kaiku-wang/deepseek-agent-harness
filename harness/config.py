"""Validated runtime configuration. Importing this module has no side effects."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    workspace: Path
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    fallback_model: str | None = None
    thinking: str = "enabled"
    reasoning_effort: str = "high"
    max_steps: int = 30
    max_output_tokens: int = 8192
    shell_timeout: int = 120
    auto_memory: bool = True

    @classmethod
    def from_env(cls, workspace: Path | None = None) -> "Settings":
        root = (workspace or Path.cwd()).resolve()
        load_dotenv(root / ".env", override=False)
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise ValueError("缺少 DEEPSEEK_API_KEY；请在项目 .env 中配置。")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path.endswith("/anthropic"):
            raise ValueError("DEEPSEEK_BASE_URL 必须是 DeepSeek 的 HTTPS OpenAI 兼容入口。")
        thinking = os.getenv("DEEPSEEK_THINKING", "enabled").lower()
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "high").lower()
        if thinking not in {"enabled", "disabled"}:
            raise ValueError("DEEPSEEK_THINKING 只能是 enabled 或 disabled。")
        if effort not in {"low", "high", "max"}:
            raise ValueError("DEEPSEEK_REASONING_EFFORT 只能是 low、high 或 max。")
        max_steps = int(os.getenv("HARNESS_MAX_STEPS", "30"))
        if not 1 <= max_steps <= 100:
            raise ValueError("HARNESS_MAX_STEPS 必须在 1 到 100 之间。")
        auto_memory_value = os.getenv("HARNESS_AUTO_MEMORY", "true").lower()
        if auto_memory_value not in {"true", "false"}:
            raise ValueError("HARNESS_AUTO_MEMORY 只能是 true 或 false。")
        return cls(
            workspace=root,
            api_key=key,
            base_url=base_url,
            model=os.getenv("MODEL_ID", "deepseek-flash").strip(),
            fallback_model=os.getenv("FALLBACK_MODEL_ID") or None,
            thinking=thinking,
            reasoning_effort=effort,
            max_steps=max_steps,
            auto_memory=auto_memory_value == "true",
        )
