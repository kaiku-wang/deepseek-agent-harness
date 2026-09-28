"""Interactive command-line entry point."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path

from .agent import Agent
from .config import Settings
from .console import ConsoleBroker


def main() -> None:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="DeepSeek coding-agent harness")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--prompt", help="单次运行的用户请求")
    args = parser.parse_args()
    try:
        settings = Settings.from_env(args.workspace)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    console = ConsoleBroker()

    def approve(kind: str, detail: str) -> bool:
        print(f"\n[权限确认] {kind}: {detail}")
        return console.ask("允许执行？[y/N] ").strip().lower() in {"y", "yes"}

    agent = Agent(settings, on_tool=lambda name, output: console.print(f"  > {name}: {output[:200]}"),
                  approval=approve)
    if args.prompt:
        print(agent.run(args.prompt))
        return
    print(f"DeepSeek Harness | {settings.model} | {settings.workspace}")
    print("输入问题后回车；输入 /exit 退出。")
    stop = threading.Event()
    agent_lock = threading.RLock()
    scheduled: queue.Queue[dict] = queue.Queue()

    for job in agent.scheduler.pending():
        scheduled.put(job)

    def scan_cron() -> None:
        while not stop.wait(1):
            for job in agent.scheduler.due():
                scheduled.put(job)

    def poll_events() -> None:
        while not stop.wait(1):
            with agent_lock:
                while not scheduled.empty():
                    job = scheduled.get_nowait()
                    prompt = f"[定时任务 {job['id']}] {job['prompt']}"
                    accepted = False
                    def acknowledge():
                        nonlocal accepted
                        agent.scheduler.acknowledge([job["id"]])
                        accepted = True
                    try:
                        console.print(f"\n{prompt}")
                        console.print(agent.run(prompt, on_accepted=acknowledge))
                    except RuntimeError as exc:
                        if not accepted:
                            agent.scheduler.restore([job["id"]])
                        console.print(f"\n定时任务失败：{exc}")
                if agent.pending_events():
                    notice = agent.collect_events()
                    if notice:
                        try:
                            console.print(f"\n{notice}")
                            console.print(agent.run(notice))
                        except RuntimeError as exc:
                            console.print(f"\n事件处理失败：{exc}")

    threading.Thread(target=scan_cron, daemon=True).start()
    threading.Thread(target=poll_events, daemon=True).start()
    try:
        while True:
            try:
                query = console.ask().strip()
            except (EOFError, KeyboardInterrupt):
                break
            if query.lower() in {"/exit", "exit", "q"}:
                break
            if query:
                try:
                    with agent_lock:
                        print(agent.run(query))
                except RuntimeError as exc:
                    print(f"错误：{exc}")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
