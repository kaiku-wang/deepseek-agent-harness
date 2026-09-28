from datetime import datetime
from pathlib import Path

import pytest

from harness.scheduler import Scheduler, cron_matches, validate_cron


def test_cron_validation_and_once_per_minute(tmp_path: Path):
    with pytest.raises(ValueError):
        validate_cron("60 * * * *")
    with pytest.raises(ValueError):
        validate_cron("1,foo * * * *")
    assert cron_matches("*/5 * * * *", datetime(2026, 9, 28, 9, 10))
    assert cron_matches("10 9 1 * 1", datetime(2026, 9, 28, 9, 10))
    scheduler = Scheduler(tmp_path)
    scheduler.schedule("* * * * *", "检查任务")
    now = datetime(2026, 9, 28, 9, 10)
    assert len(scheduler.due(now)) == 1
    assert scheduler.due(now) == []


def test_one_shot_session_job_acknowledgement(tmp_path: Path):
    scheduler = Scheduler(tmp_path)
    import json
    job = json.loads(scheduler.schedule("* * * * *", "一次性", recurring=False, durable=False))
    assert not scheduler.path.exists()
    due = scheduler.due(datetime(2026, 9, 28, 9, 10))
    assert [item["id"] for item in due] == [job["id"]]
    scheduler.restore([job["id"]])
    assert len(scheduler.due(datetime(2026, 9, 28, 9, 10))) == 1
    scheduler.acknowledge([job["id"]])
    assert scheduler.list() == "[]"


def test_durable_pending_delivery_survives_restart(tmp_path: Path):
    scheduler = Scheduler(tmp_path)
    scheduler.schedule("* * * * *", "恢复我")
    due = scheduler.due(datetime(2026, 9, 28, 9, 10))
    restarted = Scheduler(tmp_path)
    assert restarted.pending()[0]["id"] == due[0]["id"]
    restarted.acknowledge([due[0]["id"]])
    assert restarted.pending() == []
