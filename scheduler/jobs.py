from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


def build_scheduler(job_func: Callable[[], None]) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        job_func,
        CronTrigger(hour=0, minute=10, timezone="Asia/Shanghai"),
        id="collect_yesterday",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
