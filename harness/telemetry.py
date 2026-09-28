"""Structured local trace with secret-safe, bounded event payloads."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class TraceWriter:
    def __init__(self, root: Path):
        self.path = root / ".harness" / "trace.jsonl"
        self.lock = threading.Lock()

    def emit(self, event: str, **fields) -> None:
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event,
                  **{key: value for key, value in fields.items() if key not in {"api_key", "arguments", "content"}}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
