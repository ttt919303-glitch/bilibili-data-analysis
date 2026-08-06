from __future__ import annotations

import run_interaction_backfill as runner


def batch_result(
    *,
    status: str | None = None,
    updated_count: int,
    processed_count: int,
    skipped_count: int,
    retryable_count: int,
    failed_count: int,
    remaining_count: int,
) -> dict[str, object]:
    return {
        "status": status or ("partial" if failed_count else "success"),
        "planned_count": 50,
        "updated_count": updated_count,
        "processed_count": processed_count,
        "skipped_count": skipped_count,
        "retryable_count": retryable_count,
        "failed_count": failed_count,
        "remaining_count": remaining_count,
        "message": "backfill_partial" if failed_count else "backfill_complete",
    }


def test_run_all_batches_continues_until_deferred_url_succeeds(monkeypatch):
    outcomes = iter(
        [
            batch_result(
                updated_count=49,
                processed_count=50,
                skipped_count=1,
                retryable_count=1,
                failed_count=1,
                remaining_count=1,
            ),
            batch_result(
                updated_count=1,
                processed_count=1,
                skipped_count=0,
                retryable_count=0,
                failed_count=0,
                remaining_count=0,
            ),
        ]
    )
    limits = []
    reports = []

    def backfill(limit: int):
        limits.append(limit)
        return next(outcomes)

    monkeypatch.setattr(runner, "backfill_bilibili_interactions", backfill)

    result = runner.run_all_batches(report=reports.append)

    assert limits == [50, 50]
    assert len(reports) == 2
    assert result == {
        "status": "success",
        "batch_count": 2,
        "updated_count": 50,
        "processed_count": 51,
        "skipped_count": 1,
        "failed_count": 0,
        "remaining_count": 0,
    }


def test_run_all_batches_stops_when_only_exhausted_urls_remain(monkeypatch):
    monkeypatch.setattr(
        runner,
        "backfill_bilibili_interactions",
        lambda limit: batch_result(
            updated_count=0,
            processed_count=0,
            skipped_count=0,
            retryable_count=0,
            failed_count=2,
            remaining_count=2,
        ),
    )

    result = runner.run_all_batches(report=lambda _result: None)

    assert result["status"] == "partial"
    assert result["batch_count"] == 1
    assert result["failed_count"] == 2
    assert result["remaining_count"] == 2


def test_run_all_batches_stops_on_real_verification_fuse(monkeypatch):
    calls = []

    def backfill(limit: int):
        calls.append(limit)
        return batch_result(
            status="verification_required",
            updated_count=10,
            processed_count=12,
            skipped_count=2,
            retryable_count=100,
            failed_count=2,
            remaining_count=100,
        )

    monkeypatch.setattr(runner, "backfill_bilibili_interactions", backfill)

    result = runner.run_all_batches(report=lambda _result: None)

    assert calls == [50]
    assert result["status"] == "verification_required"
    assert result["remaining_count"] == 100


def test_run_target_batches_forwards_requested_urls_and_runtime_paths(monkeypatch, tmp_path):
    target_urls = [
        "https://www.bilibili.com/video/BV1newA",
        "https://www.bilibili.com/video/BV1newB",
    ]
    calls = []

    data_path = tmp_path / "videos.csv"
    state_path = tmp_path / "backfill-state.json"

    def backfill(limit: int, target_urls=None, data_path=None, state_path=None):
        calls.append((limit, list(target_urls or []), data_path, state_path))
        return batch_result(
            updated_count=2,
            processed_count=2,
            skipped_count=0,
            retryable_count=0,
            failed_count=0,
            remaining_count=0,
        )

    monkeypatch.setattr(runner, "backfill_bilibili_interactions", backfill)

    result = runner.run_target_batches(
        target_urls,
        report=lambda _result: None,
        data_path=data_path,
        state_path=state_path,
    )

    assert calls == [(50, target_urls, data_path, state_path)]
    assert result["status"] == "success"
    assert result["updated_count"] == 2
