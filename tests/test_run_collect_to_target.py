from __future__ import annotations

import run_collect_to_target as collector


def backfill_result(status: str) -> dict[str, object]:
    return {
        "status": status,
        "batch_count": 1,
        "updated_count": 0,
        "processed_count": 0,
        "skipped_count": 0,
        "failed_count": 1 if status != "success" else 0,
        "remaining_count": 1 if status != "success" else 0,
    }


def test_target_rows_are_not_complete_until_interactions_are_backfilled(monkeypatch):
    monkeypatch.setattr(collector, "_configure_logging", lambda: None)
    monkeypatch.setattr(collector, "_row_count", lambda: collector.TARGET_ROWS)
    monkeypatch.setattr(
        collector,
        "run_all_batches",
        lambda report: backfill_result("verification_required"),
        raising=False,
    )

    assert collector.main() == 6


def test_final_search_batch_collects_only_the_missing_row_count(monkeypatch):
    state = {"rows": collector.TARGET_ROWS - 3}
    limits: list[int] = []

    def crawl(_keyword: str, limit: int) -> dict[str, object]:
        limits.append(limit)
        state["rows"] += limit
        return {
            "status": "success",
            "parsed_count": limit,
            "skipped_count": 0,
            "message": "collection_complete",
        }

    monkeypatch.setattr(collector, "_configure_logging", lambda: None)
    monkeypatch.setattr(collector, "_row_count", lambda: state["rows"])
    monkeypatch.setattr(collector, "crawl_bilibili_browser", crawl)
    monkeypatch.setattr(collector, "KEYWORDS", ("Python",))
    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        collector,
        "run_all_batches",
        lambda report: backfill_result("success"),
        raising=False,
    )

    assert collector.main() == 0
    assert limits == [3]


def test_each_search_batch_collects_details_before_the_next_search_batch(monkeypatch):
    state = {"rows": collector.TARGET_ROWS - 4}
    events: list[str] = []

    def crawl(keyword: str, limit: int) -> dict[str, object]:
        events.append(f"crawl:{keyword}")
        state["rows"] += limit
        return {
            "status": "success",
            "parsed_count": limit,
            "skipped_count": 0,
            "message": "collection_complete",
        }

    def collect_details(report):
        events.append("details")
        result = backfill_result("partial")
        result["updated_count"] = 2
        return result

    monkeypatch.setattr(collector, "_configure_logging", lambda: None)
    monkeypatch.setattr(collector, "_row_count", lambda: state["rows"])
    monkeypatch.setattr(collector, "crawl_bilibili_browser", crawl)
    monkeypatch.setattr(collector, "run_all_batches", collect_details)
    monkeypatch.setattr(collector, "KEYWORDS", ("Python", "Java"))
    monkeypatch.setattr(collector, "BATCH_SIZE", 2)
    monkeypatch.setattr(collector.time, "sleep", lambda _seconds: None)

    assert collector.main() == 0
    assert events == ["crawl:Python", "details", "crawl:Java", "details"]
