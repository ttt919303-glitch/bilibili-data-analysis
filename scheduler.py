from __future__ import annotations

import os
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from daily_pipeline import run_daily_pipeline


_scheduler = None
_scheduler_lock = threading.Lock()


def _enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def start_scheduler(app):
    global _scheduler
    if app.config.get("TESTING") or os.getenv("PYTEST_CURRENT_TEST"):
        return None
    if not _enabled(app.config.get("AUTO_CRAWL_ENABLED", False)):
        return None
    if app.debug and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return None

    with _scheduler_lock:
        if _scheduler is not None:
            return _scheduler
        scheduler = BackgroundScheduler(timezone=app.config["APP_TIMEZONE"])
        scheduler.add_job(
            lambda: run_daily_pipeline(config=app.config.copy()),
            "cron",
            hour=0,
            minute=0,
            id="daily-bilibili-pipeline",
            replace_existing=True,
        )
        scheduler.start()
        _scheduler = scheduler
        return scheduler
