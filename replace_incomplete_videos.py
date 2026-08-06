"""Recoverably replace incomplete Bilibili rows with real fully detailed videos."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import cycle
from pathlib import Path
from time import sleep
from typing import Any

import pandas as pd

from browser_interaction_backfill import (
    _load_backfill_state,
    _save_backfill_state,
    _video_urls,
    get_supported_video_urls,
    normalize_backfill_url,
)
from browser_crawler import BrowserCrawlerError, crawl_bilibili_browser
from data_utils import load_video_data, save_video_data
from run_collect_to_target import KEYWORDS
from run_interaction_backfill import run_target_batches


PROJECT_DIR = Path(__file__).resolve().parent
DATA_PATH = PROJECT_DIR / "data" / "videos.csv"
STATE_PATH = PROJECT_DIR / "data" / "interaction_backfill_state.json"
BACKUP_ROOT = PROJECT_DIR / "data" / "backups"
PLAN_PATH = PROJECT_DIR / "data" / "replacement_plan.json"
LOG_PATH = PROJECT_DIR / "data" / "replacement_collection.log"
BATCH_SIZE = 200
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplacementPlan:
    data_path: Path
    state_path: Path
    backup_dir: Path
    plan_path: Path
    removed_urls: tuple[str, ...]
    removed_url_count: int
    removed_row_count: int
    initial_completed_count: int
    target_completed_count: int

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for key in ("data_path", "state_path", "backup_dir", "plan_path"):
            values[key] = str(values[key])
        values["removed_urls"] = list(self.removed_urls)
        return values

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ReplacementPlan":
        data = dict(values)
        for key in ("data_path", "state_path", "backup_dir", "plan_path"):
            data[key] = Path(data[key])
        data["removed_urls"] = tuple(data["removed_urls"])
        return cls(**data)


def _atomic_save_data(data, path: Path) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.replacement.tmp")
    save_video_data(data, temporary_path)
    temporary_path.replace(path)


def _atomic_write_json(path: Path, value: object) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def load_replacement_plan(path: Path = PLAN_PATH) -> ReplacementPlan:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("replacement plan must be a JSON object")
    return ReplacementPlan.from_dict(values)


def _normalized_urls(data):
    return data["video_url"].map(lambda value: normalize_backfill_url(str(value).strip()))


def _backup_sources(data_path: Path, state_path: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(data_path, backup_dir / data_path.name)
    shutil.copy2(state_path, backup_dir / state_path.name)
    return backup_dir


def prepare_replacement(
    *,
    data_path: Path = DATA_PATH,
    state_path: Path = STATE_PATH,
    backup_root: Path = BACKUP_ROOT,
    plan_path: Path = PLAN_PATH,
) -> ReplacementPlan:
    if plan_path.exists():
        raise FileExistsError(f"replacement plan already exists: {plan_path}")

    data = load_video_data(data_path)
    if data.empty:
        raise ValueError("videos.csv does not contain any rows")
    completed_urls, failed_urls = _load_backfill_state(state_path)
    video_urls = _video_urls(data)
    incomplete_urls = [url for url in video_urls if url not in completed_urls]
    if not incomplete_urls:
        raise ValueError("videos.csv does not contain incomplete supported URLs")

    normalized_urls = _normalized_urls(data)
    remove_mask = normalized_urls.isin(incomplete_urls)
    removed_row_count = int(remove_mask.sum())
    remaining_data = data.loc[~remove_mask].copy()
    remaining_urls = set(_video_urls(remaining_data))
    remaining_completed = completed_urls & remaining_urls
    remaining_failures = {url: failure for url, failure in failed_urls.items() if url in remaining_urls}

    backup_dir = _backup_sources(data_path, state_path, backup_root)
    _atomic_save_data(remaining_data, data_path)
    _save_backfill_state(state_path, remaining_completed, remaining_failures)

    plan = ReplacementPlan(
        data_path=data_path,
        state_path=state_path,
        backup_dir=backup_dir,
        plan_path=plan_path,
        removed_urls=tuple(incomplete_urls),
        removed_url_count=len(incomplete_urls),
        removed_row_count=removed_row_count,
        initial_completed_count=len(remaining_completed),
        target_completed_count=len(remaining_completed) + len(incomplete_urls),
    )
    _atomic_write_json(plan_path, plan.to_dict())
    return plan


def remove_target_urls(
    target_urls,
    *,
    data_path: Path = DATA_PATH,
    state_path: Path = STATE_PATH,
) -> int:
    normalized_targets = {
        video_url
        for value in target_urls
        if (video_url := normalize_backfill_url(str(value).strip())) is not None
    }
    data = load_video_data(data_path)
    completed_urls, failed_urls = _load_backfill_state(state_path)
    completed_targets = normalized_targets & completed_urls
    if completed_targets:
        raise ValueError(f"refusing to remove completed URL: {sorted(completed_targets)[0]}")

    remove_mask = _normalized_urls(data).isin(normalized_targets)
    removed_row_count = int(remove_mask.sum())
    if removed_row_count == 0:
        return 0

    _atomic_save_data(data.loc[~remove_mask].copy(), data_path)
    remaining_failures = {
        url: failure for url, failure in failed_urls.items() if url not in normalized_targets
    }
    _save_backfill_state(state_path, completed_urls, remaining_failures)
    return removed_row_count


def _completed_urls_in_data(plan: ReplacementPlan) -> set[str]:
    completed_urls, _failed_urls = _load_backfill_state(plan.state_path)
    return set(get_supported_video_urls(plan.data_path)) & completed_urls


def _report_detail_batch(result: dict[str, object]) -> None:
    LOGGER.info(
        "detail_batch=%s status=%s updated=%s processed=%s skipped=%s remaining=%s",
        result.get("batch"),
        result.get("status"),
        result.get("updated_count"),
        result.get("processed_count"),
        result.get("skipped_count"),
        result.get("remaining_count"),
    )


def collect_replacements(
    plan: ReplacementPlan,
    *,
    keywords=KEYWORDS,
) -> dict[str, object]:
    keyword_values = tuple(keywords)
    if not keyword_values:
        raise ValueError("replacement collection requires at least one keyword")

    keyword_iterator = cycle(keyword_values)
    stalled_batches = 0
    batch_number = 0
    while True:
        completed_urls = _completed_urls_in_data(plan)
        if len(completed_urls) >= plan.target_completed_count:
            return {
                "status": "success",
                "completed_count": len(completed_urls),
                "target_completed_count": plan.target_completed_count,
                "batch_count": batch_number,
            }

        before_urls = get_supported_video_urls(plan.data_path)
        pending_urls = [url for url in before_urls if url not in completed_urls]
        if pending_urls:
            detail_result = run_target_batches(pending_urls, report=_report_detail_batch)
            if detail_result["status"] == "verification_required":
                return {
                    "status": "verification_required",
                    "completed_count": len(_completed_urls_in_data(plan)),
                    "target_completed_count": plan.target_completed_count,
                    "batch_count": batch_number,
                }
            updated_completed = _completed_urls_in_data(plan)
            failed_pending = [url for url in pending_urls if url not in updated_completed]
            if failed_pending:
                remove_target_urls(
                    failed_pending,
                    data_path=plan.data_path,
                    state_path=plan.state_path,
                )
            continue

        needed_count = plan.target_completed_count - len(completed_urls)
        keyword = next(keyword_iterator)
        batch_number += 1
        limit = min(BATCH_SIZE, needed_count)
        result = crawl_bilibili_browser(keyword, limit)
        after_urls = get_supported_video_urls(plan.data_path)
        existing_urls = set(before_urls)
        new_urls = [url for url in after_urls if url not in existing_urls]
        LOGGER.info(
            "search_batch=%s keyword=%s status=%s planned=%s saved=%s new_urls=%s completed=%s target=%s",
            batch_number,
            keyword,
            result.get("status"),
            limit,
            result.get("saved_count", 0),
            len(new_urls),
            len(completed_urls),
            plan.target_completed_count,
        )

        if result.get("status") == "verification_required":
            return {
                "status": "verification_required",
                "completed_count": len(completed_urls),
                "target_completed_count": plan.target_completed_count,
                "batch_count": batch_number,
            }
        if not new_urls:
            stalled_batches += 1
            if stalled_batches >= len(keyword_values) * 2:
                raise RuntimeError("replacement collection produced no new URLs for two keyword cycles")
            sleep(2)
            continue

        stalled_batches = 0
        detail_result = run_target_batches(new_urls, report=_report_detail_batch)
        if detail_result["status"] == "verification_required":
            return {
                "status": "verification_required",
                "completed_count": len(_completed_urls_in_data(plan)),
                "target_completed_count": plan.target_completed_count,
                "batch_count": batch_number,
            }

        updated_completed = _completed_urls_in_data(plan)
        failed_new_urls = [url for url in new_urls if url not in updated_completed]
        if failed_new_urls:
            remove_target_urls(
                failed_new_urls,
                data_path=plan.data_path,
                state_path=plan.state_path,
            )
        if len(updated_completed) >= plan.target_completed_count:
            return {
                "status": "success",
                "completed_count": len(updated_completed),
                "target_completed_count": plan.target_completed_count,
                "batch_count": batch_number,
            }
        sleep(2)


def verify_replacement(plan: ReplacementPlan) -> dict[str, int]:
    data = load_video_data(plan.data_path)
    video_urls = _video_urls(data)
    completed_urls = _completed_urls_in_data(plan)
    incomplete_urls = set(video_urls) - completed_urls
    non_video_urls = [url for url in video_urls if "/video/" not in url]
    metric_columns = [
        "play_count",
        "like_count",
        "coin_count",
        "favorite_count",
        "share_count",
    ]
    invalid_metric_count = 0
    for column in metric_columns:
        numeric_values = pd.to_numeric(data[column], errors="coerce")
        invalid_metric_count += int((numeric_values.isna() | (numeric_values < 0)).sum())
    missing_crawl_date_count = int((data["crawl_date"].astype(str).str.strip() == "").sum())

    if len(video_urls) != plan.target_completed_count:
        raise RuntimeError(
            f"replacement verification expected {plan.target_completed_count} unique URLs, got {len(video_urls)}"
        )
    if len(completed_urls) != plan.target_completed_count or incomplete_urls:
        raise RuntimeError(
            f"replacement verification found {len(incomplete_urls)} incomplete URLs"
        )
    if non_video_urls:
        raise RuntimeError(f"replacement verification found a non-video URL: {non_video_urls[0]}")
    if invalid_metric_count:
        raise RuntimeError(
            f"replacement verification found {invalid_metric_count} invalid metric values"
        )
    if missing_crawl_date_count:
        raise RuntimeError(
            f"replacement verification found {missing_crawl_date_count} missing crawl dates"
        )

    return {
        "unique_video_count": len(video_urls),
        "completed_count": len(completed_urls),
        "incomplete_count": len(incomplete_urls),
        "invalid_metric_count": invalid_metric_count,
        "missing_crawl_date_count": missing_crawl_date_count,
    }


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    logging.getLogger().addHandler(logging.StreamHandler())


def main() -> int:
    _configure_logging()
    plan = load_replacement_plan() if PLAN_PATH.exists() else prepare_replacement()
    print(
        json.dumps(
            {
                "event": "replacement_ready",
                "removed_url_count": plan.removed_url_count,
                "removed_row_count": plan.removed_row_count,
                "initial_completed_count": plan.initial_completed_count,
                "target_completed_count": plan.target_completed_count,
                "backup_dir": str(plan.backup_dir),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        result = collect_replacements(plan)
    except BrowserCrawlerError:
        LOGGER.exception("replacement browser collection failed to start")
        return 2
    print(json.dumps({"event": "replacement_collection", **result}, ensure_ascii=False), flush=True)
    if result["status"] == "verification_required":
        return 3
    summary = verify_replacement(plan)
    print(json.dumps({"event": "replacement_complete", **summary}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
