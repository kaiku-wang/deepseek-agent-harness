"""Durable five-field cron jobs; due jobs are claimed atomically per process."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path


RANGES = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]


def _matches(field: str, number: int, low: int, high: int) -> bool:
    for item in field.split(","):
        try:
            if item == "*":
                return True
            base, *step_part = item.split("/")
            step = int(step_part[0]) if step_part else 1
            if step <= 0 or len(step_part) > 1:
                return False
            if base == "*":
                start, end = low, high
            elif "-" in base:
                start, end = map(int, base.split("-", 1))
            else:
                start = end = int(base)
            if low <= start <= number <= end <= high and (number - start) % step == 0:
                return True
        except ValueError:
            return False
    return False


def validate_cron(expression: str) -> None:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron 表达式必须有五个字段")
    for field, (low, high) in zip(fields, RANGES):
        for item in field.split(","):
            if not item:
                raise ValueError(f"cron 字段无效：{field}")
            base, *step_part = item.split("/")
            if len(step_part) > 1 or (step_part and (not step_part[0].isdigit() or int(step_part[0]) <= 0)):
                raise ValueError(f"cron 步长无效：{item}")
            if base == "*":
                continue
            try:
                if "-" in base:
                    start, end = map(int, base.split("-", 1))
                else:
                    start = end = int(base)
            except ValueError as exc:
                raise ValueError(f"cron 字段无效：{item}") from exc
            if not (low <= start <= end <= high):
                raise ValueError(f"cron 范围无效：{item}")


def cron_matches(expression: str, when: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    if not (_matches(minute, when.minute, 0, 59)
            and _matches(hour, when.hour, 0, 23)
            and _matches(month, when.month, 1, 12)):
        return False
    day_ok = _matches(day, when.day, 1, 31)
    weekday_ok = _matches(weekday, (when.weekday() + 1) % 7, 0, 6)
    if day == "*":
        return weekday_ok
    if weekday == "*":
        return day_ok
    return day_ok or weekday_ok


class Scheduler:
    def __init__(self, root: Path):
        self.path = root / ".harness" / "cron.json"
        self.lock = threading.RLock()
        self.session_jobs: list[dict] = []

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def _save(self, jobs: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def schedule(self, cron: str, prompt: str, recurring: bool = True,
                 durable: bool = True) -> str:
        validate_cron(cron)
        if not prompt.strip():
            raise ValueError("任务提示不能为空")
        with self.lock:
            jobs = self._load()
            job = {"id": f"cron_{uuid.uuid4().hex[:8]}", "cron": cron,
                   "prompt": prompt, "recurring": recurring, "durable": durable,
                   "last_run": None, "pending_delivery": False}
            if durable:
                jobs.append(job)
                self._save(jobs)
            else:
                self.session_jobs.append(job)
            return json.dumps(job, ensure_ascii=False)

    def list(self) -> str:
        with self.lock:
            return json.dumps(self._load() + self.session_jobs, ensure_ascii=False, indent=2)

    def cancel(self, job_id: str) -> str:
        with self.lock:
            jobs = self._load()
            remaining = [job for job in jobs if job["id"] != job_id]
            session_remaining = [job for job in self.session_jobs if job["id"] != job_id]
            if len(jobs) == len(remaining) and len(self.session_jobs) == len(session_remaining):
                raise ValueError("定时任务不存在")
            self._save(remaining)
            self.session_jobs = session_remaining
            return f"已取消 {job_id}"

    def due(self, when: datetime | None = None) -> list[dict]:
        now = when or datetime.now()
        minute = now.strftime("%Y-%m-%dT%H:%M")
        with self.lock:
            jobs = self._load()
            due = []
            for job in jobs + self.session_jobs:
                if (not job.get("pending_delivery") and job.get("last_run") != minute
                        and cron_matches(job["cron"], now)):
                    due.append(dict(job))
                    job["last_run"] = minute
                    job["pending_delivery"] = True
            if due:
                self._save(jobs)
            return due

    def pending(self) -> list[dict]:
        """Recover durable deliveries left unacknowledged after a restart."""
        with self.lock:
            return [dict(job) for job in self._load() if job.get("pending_delivery")]

    def acknowledge(self, job_ids: list[str]) -> None:
        with self.lock:
            jobs = self._load()
            for collection in (jobs, self.session_jobs):
                collection[:] = [job for job in collection
                                 if job["id"] not in job_ids or job.get("recurring", True)]
                for job in collection:
                    if job["id"] in job_ids:
                        job["pending_delivery"] = False
            self._save(jobs)

    def restore(self, job_ids: list[str]) -> None:
        with self.lock:
            jobs = self._load()
            for job in jobs + self.session_jobs:
                if job["id"] in job_ids:
                    job["pending_delivery"], job["last_run"] = False, None
            self._save(jobs)
