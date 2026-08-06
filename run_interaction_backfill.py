"""Run every eligible Bilibili interaction backfill batch to completion."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from collections.abc import Iterable
from pathlib import Path

from browser_interaction_backfill import (
    BACKFILL_LIMIT,
    backfill_bilibili_interactions,
    get_backfill_progress,
    reset_exhausted_failures,
)


def print_report(result: dict[str, object]) -> None:
    print(json.dumps({"event": "batch_finished", **result}, ensure_ascii=False), flush=True)


def _run_batches(
    target_urls: Iterable[str] | None,
    report: Callable[[dict[str, object]], None] = print_report,
    data_path: Path | None = None,
    state_path: Path | None = None,
) -> dict[str, object]:
    requested_urls = list(target_urls) if target_urls is not None else None
    batch_count = 0
    updated_count = 0
    processed_count = 0
    skipped_count = 0

    while True:
        call_arguments = {"limit": BACKFILL_LIMIT}
        if requested_urls is not None:
            call_arguments["target_urls"] = requested_urls
        if data_path is not None:
            call_arguments["data_path"] = data_path
        if state_path is not None:
            call_arguments["state_path"] = state_path
        result = backfill_bilibili_interactions(**call_arguments)
        batch_count += 1
        updated_count += int(result["updated_count"])
        processed_count += int(result["processed_count"])
        skipped_count += int(result["skipped_count"])
        report({"batch": batch_count, **result})

        if result["status"] == "verification_required":
            return {
                "status": "verification_required",
                "batch_count": batch_count,
                "updated_count": updated_count,
                "processed_count": processed_count,
                "skipped_count": skipped_count,
                "failed_count": int(result["failed_count"]),
                "remaining_count": int(result["remaining_count"]),
            }
        retryable_count = int(result["retryable_count"])
        if retryable_count == 0:
            remaining_count = int(result["remaining_count"])
            return {
                "status": "success" if remaining_count == 0 else "partial",
                "batch_count": batch_count,
                "updated_count": updated_count,
                "processed_count": processed_count,
                "skipped_count": skipped_count,
                "failed_count": int(result["failed_count"]),
                "remaining_count": remaining_count,
            }
        if int(result["processed_count"]) == 0:
            raise RuntimeError("backfill reported retryable URLs without processing any URL")


def run_all_batches(
    report: Callable[[dict[str, object]], None] = print_report,
    *,
    data_path: Path | None = None,
    state_path: Path | None = None,
) -> dict[str, object]:
    return _run_batches(None, report, data_path, state_path)


def run_target_batches(
    target_urls: Iterable[str],
    report: Callable[[dict[str, object]], None] = print_report,
    *,
    data_path: Path | None = None,
    state_path: Path | None = None,
) -> dict[str, object]:
    return _run_batches(target_urls, report, data_path, state_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retry-exhausted",
        action="store_true",
        help="start one new retry cycle for exhausted normal video URLs",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.retry_exhausted:
        print(
            json.dumps(
                {"event": "retry_cycle_started", "reset_count": reset_exhausted_failures()},
                ensure_ascii=False,
            ),
            flush=True,
        )
    print(
        json.dumps({"event": "started", **get_backfill_progress()}, ensure_ascii=False),
        flush=True,
    )
    result = run_all_batches()
    print(json.dumps({"event": "finished", **result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
