"""Asynchronous shell jobs with one-shot result notifications."""

from __future__ import annotations

import threading
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class BackgroundJob:
    id: str
    command: str
    status: str = "running"
    result: str = ""
    cwd: Path | None = None


class BackgroundManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.jobs: dict[str, BackgroundJob] = {}
        self.counter = 0

    def start(self, command: str, runner: Callable[[], str], cwd: Path | None = None) -> str:
        with self.lock:
            self.counter += 1
            job = BackgroundJob(f"bg_{self.counter:04d}", command, cwd=cwd)
            self.jobs[job.id] = job

        def work():
            try:
                result = runner()
                exit_match = re.match(r"exit_code=(\d+)", result)
                status = "failed" if result.startswith("Error:") or (exit_match and int(exit_match.group(1))) else "completed"
            except Exception as exc:
                result, status = f"Error: {type(exc).__name__}: {exc}", "failed"
            with self.lock:
                job.result, job.status = result, status

        threading.Thread(target=work, daemon=True, name=job.id).start()
        return f"[Background task {job.id} started] Result will arrive as a task_notification."

    def has_ready(self) -> bool:
        with self.lock:
            return any(job.status != "running" for job in self.jobs.values())

    def running_in(self, directory: Path) -> bool:
        with self.lock:
            return any(job.status == "running" and job.cwd == directory
                       for job in self.jobs.values())

    def collect(self) -> list[str]:
        with self.lock:
            ready = [job for job in self.jobs.values() if job.status != "running"]
            for job in ready:
                self.jobs.pop(job.id, None)
        return [
            "<task_notification>\n"
            f"<task_id>{job.id}</task_id>\n"
            f"<status>{job.status}</status>\n"
            f"<command>{job.command}</command>\n"
            f"<summary>{job.result[:200]}</summary>\n"
            "</task_notification>"
            for job in ready
        ]
