"""Discover local SKILL.md files without executing their contents."""

from __future__ import annotations

from pathlib import Path

import yaml


class SkillCatalog:
    def __init__(self, workspace: Path):
        self.root = workspace / "skills"

    def _entries(self) -> dict[str, tuple[str, Path]]:
        result = {}
        if not self.root.exists():
            return result
        for path in self.root.glob("*/SKILL.md"):
            if not path.resolve().is_relative_to(self.root.resolve()):
                continue
            text = path.read_text(encoding="utf-8")
            meta = {}
            if text.startswith("---\n"):
                parts = text.split("---\n", 2)
                if len(parts) == 3:
                    try:
                        meta = yaml.safe_load(parts[1]) or {}
                    except yaml.YAMLError:
                        pass
            if not isinstance(meta, dict):
                meta = {}
            name = str(meta.get("name") or path.parent.name)
            description = str(meta.get("description") or "").strip()
            result[name] = (description, path)
        return result

    def list(self) -> str:
        entries = self._entries()
        return "\n".join(f"- {name}: {description}" for name, (description, _) in entries.items()) or "(无本地技能)"

    def load(self, name: str) -> str:
        entries = self._entries()
        if name not in entries:
            raise ValueError(f"技能不存在：{name}")
        return entries[name][1].read_text(encoding="utf-8")
