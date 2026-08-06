"""Collect real Bilibili search results until videos.csv reaches the target size."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from browser_crawler import BrowserCrawlerError, crawl_bilibili_browser
from data_utils import load_video_data
from run_interaction_backfill import run_all_batches

TARGET_ROWS = 10_000
BATCH_SIZE = 200
DATA_PATH = Path(__file__).resolve().parent / "data" / "videos.csv"
LOG_PATH = Path(__file__).resolve().parent / "data" / "collection_to_10000.log"
KEYWORDS = (
    "Python",
    "机器学习",
    "深度学习",
    "人工智能",
    "数据分析",
    "大数据",
    "编程教程",
    "计算机基础",
    "算法",
    "自然语言处理",
    "计算机视觉",
    "数据结构",
    "数据库",
    "Java",
    "前端开发",
    "后端开发",
    "软件工程",
    "网络安全",
    "云计算",
    "Linux",
    "TensorFlow",
    "PyTorch",
    "机器视觉",
    "程序员",
    "科技",
)


def _configure_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    logging.getLogger().addHandler(logging.StreamHandler())


def _row_count() -> int:
    return len(load_video_data(DATA_PATH))


def _report_backfill_batch(result: dict[str, object]) -> None:
    logging.info(
        "backfill_batch=%s status=%s updated=%s processed=%s skipped=%s remaining=%s",
        result.get("batch"),
        result.get("status"),
        result.get("updated_count"),
        result.get("processed_count"),
        result.get("skipped_count"),
        result.get("remaining_count"),
    )


def _backfill_pending_interactions(required_updates: int | None = None) -> int:
    result = run_all_batches(report=_report_backfill_batch)
    logging.info(
        "interaction_backfill_finished status=%s updated=%s failed=%s remaining=%s",
        result["status"],
        result["updated_count"],
        result["failed_count"],
        result["remaining_count"],
    )
    if result["status"] == "success":
        return 0
    if result["status"] == "verification_required":
        logging.error("workflow_stopped verification_required")
        return 6
    if required_updates is not None and int(result["updated_count"]) >= required_updates:
        logging.info("detail_collection_complete required=%s", required_updates)
        return 0
    logging.error("workflow_stopped interaction_backfill_partial")
    return 7


def main() -> int:
    _configure_logging()
    start_count = _row_count()
    logging.info("collection_started rows=%s target=%s", start_count, TARGET_ROWS)
    if start_count >= TARGET_ROWS:
        logging.info("collection_target_reached rows=%s", start_count)
        backfill_status = _backfill_pending_interactions()
        if backfill_status == 0:
            logging.info("workflow_complete rows=%s", _row_count())
        return backfill_status

    stalled_batches = 0
    for batch_number, keyword in enumerate(KEYWORDS, start=1):
        before_count = _row_count()
        if before_count >= TARGET_ROWS:
            logging.info("collection_target_reached rows=%s", before_count)
            backfill_status = _backfill_pending_interactions()
            if backfill_status == 0:
                logging.info("workflow_complete rows=%s", _row_count())
            return backfill_status

        try:
            result = crawl_bilibili_browser(keyword, min(BATCH_SIZE, TARGET_ROWS - before_count))
        except BrowserCrawlerError:
            logging.exception("browser_start_failed keyword=%s", keyword)
            return 2

        after_count = _row_count()
        added_count = after_count - before_count
        logging.info(
            "batch=%s keyword=%s status=%s added=%s rows=%s parsed=%s skipped=%s message=%s",
            batch_number,
            keyword,
            result.get("status"),
            added_count,
            after_count,
            result.get("parsed_count", 0),
            result.get("skipped_count", 0),
            result.get("message", ""),
        )

        if result.get("status") == "verification_required":
            logging.error("collection_stopped verification_required")
            return 3
        if added_count > 0:
            backfill_status = _backfill_pending_interactions(added_count)
            if backfill_status != 0:
                return backfill_status
        if added_count == 0:
            stalled_batches += 1
        else:
            stalled_batches = 0
        if after_count >= TARGET_ROWS:
            logging.info("collection_target_reached rows=%s", after_count)
            logging.info("workflow_complete rows=%s", after_count)
            return 0
        if stalled_batches >= len(KEYWORDS):
            logging.error("collection_stopped no_new_rows rows=%s", after_count)
            return 4
        time.sleep(2)

    final_count = _row_count()
    logging.error("collection_stopped keyword_list_exhausted rows=%s target=%s", final_count, TARGET_ROWS)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
