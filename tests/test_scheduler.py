import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scheduler.jobs import build_scheduler


def test_local_datetime_works_without_zoneinfo_module():
    project_root = Path(__file__).resolve().parents[1]
    script = """
import builtins
from datetime import timedelta

original_import = builtins.__import__

def import_without_zoneinfo(name, globals=None, *args, **kwargs):
    source = globals.get("__file__", "") if globals else ""
    if name == "zoneinfo" and source.endswith("app.py"):
        raise ModuleNotFoundError("No module named 'zoneinfo'")
    return original_import(name, globals, *args, **kwargs)

builtins.__import__ = import_without_zoneinfo
from app import current_local_datetime

assert current_local_datetime().utcoffset() == timedelta(hours=8)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_scheduler_registers_single_daily_job_at_0010():
    scheduler = build_scheduler(lambda: None)
    jobs = scheduler.get_jobs()

    assert len(jobs) == 1
    assert jobs[0].id == "collect_yesterday"
    fields = jobs[0].trigger.fields
    assert str(fields[5]) == "0"
    assert str(fields[6]) == "10"


def test_scheduled_collection_archives_to_yesterday(app, monkeypatch):
    created = []
    executed = []
    monkeypatch.setattr(
        "app.current_local_datetime", lambda: datetime(2026, 8, 9, 0, 10)
    )
    monkeypatch.setattr(
        "app.create_task",
        lambda keyword, target, date: created.append((keyword, target, date)) or 12,
    )
    monkeypatch.setattr(
        "app.run_collection_task",
        lambda app, task_id, keyword, target, date: executed.append((task_id, date)),
    )
    monkeypatch.setattr(
        "app.clean_video_data",
        lambda rows: pytest.fail("scheduler must not clean data directly"),
    )

    from app import run_scheduled_collection

    run_scheduled_collection(app)

    assert created[0][2] == "2026-08-08"
    assert executed == [(12, "2026-08-08")]


def test_test_app_does_not_start_scheduler(app):
    assert "course_scheduler" not in app.extensions
