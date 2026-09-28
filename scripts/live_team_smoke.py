"""Optional paid DeepSeek smoke test for a persistent teammate and mailbox."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.config import Settings
from harness.provider import DeepSeekProvider
from harness.tasks import TaskStore
from harness.team import TeamManager
from harness.worktrees import WorktreeManager


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = Settings.from_env(Path(__file__).resolve().parents[1])
    provider = DeepSeekProvider(settings)
    with tempfile.TemporaryDirectory(prefix="deepseek-team-smoke-") as directory:
        root = Path(directory)
        team = TeamManager(root, provider, TaskStore(root), WorktreeManager(root), 5)
        team.spawn("smoke", "tester", "只回复 TEAM_READY，不调用工具。")
        deadline = time.monotonic() + 45
        result_seen = False
        while time.monotonic() < deadline:
            events = team.lead_events()
            if any(event["type"] == "result" and "TEAM_READY" in event["content"]
                   for event in events):
                result_seen = True
                break
            time.sleep(0.2)
        if not result_seen:
            raise RuntimeError("未在 45 秒内收到队友结果")
        team.request_shutdown("smoke")
        while time.monotonic() < deadline:
            if any(event["type"] == "shutdown_response" for event in team.lead_events()):
                print("TEAM_READY + shutdown_response")
                return
            time.sleep(0.2)
        raise RuntimeError("未收到队友退出确认")


if __name__ == "__main__":
    main()
