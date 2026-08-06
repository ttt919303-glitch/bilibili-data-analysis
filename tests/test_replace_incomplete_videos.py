from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import replace_incomplete_videos as replacement
from data_utils import VIDEO_COLUMNS, load_video_data


def video_row(video_url: str, title: str) -> dict[str, object]:
    return {
        "title": title,
        "video_url": video_url,
        "up_name": "测试UP",
        "play_count": 100,
        "like_count": 20,
        "coin_count": 3,
        "favorite_count": 4,
        "share_count": 5,
        "comment_count": 0,
        "publish_time": "2026-08-01",
        "crawl_date": "2026-08-05",
    }


def write_fixture(data_path: Path, state_path: Path) -> tuple[str, str, str]:
    completed_url = "https://www.bilibili.com/video/BV1complete"
    failed_url = "https://www.bilibili.com/video/BV1failed"
    untracked_url = "https://www.bilibili.com/video/BV1untracked"
    pd.DataFrame(
        [
            video_row(completed_url, "完整视频"),
            video_row(failed_url, "失败视频"),
            video_row(failed_url, "失败视频重复行"),
            video_row(untracked_url, "未处理视频"),
        ],
        columns=VIDEO_COLUMNS,
    ).to_csv(data_path, index=False, encoding="utf-8-sig")
    state_path.write_text(
        json.dumps(
            {
                "completed_urls": [completed_url],
                "failed_urls": {
                    failed_url: {"attempts": 1, "reason": "page_timeout"},
                },
            }
        ),
        encoding="utf-8",
    )
    return completed_url, failed_url, untracked_url


def test_prepare_replacement_backs_up_and_removes_every_incomplete_row(tmp_path):
    data_path = tmp_path / "videos.csv"
    state_path = tmp_path / "interaction_backfill_state.json"
    backup_root = tmp_path / "backups"
    plan_path = tmp_path / "replacement_plan.json"
    completed_url, failed_url, untracked_url = write_fixture(data_path, state_path)
    original_csv = data_path.read_bytes()
    original_state = state_path.read_bytes()

    plan = replacement.prepare_replacement(
        data_path=data_path,
        state_path=state_path,
        backup_root=backup_root,
        plan_path=plan_path,
    )

    remaining = load_video_data(data_path)
    assert remaining["video_url"].tolist() == [completed_url]
    assert plan.removed_url_count == 2
    assert plan.removed_row_count == 3
    assert plan.initial_completed_count == 1
    assert plan.target_completed_count == 3
    assert (plan.backup_dir / "videos.csv").read_bytes() == original_csv
    assert (plan.backup_dir / "interaction_backfill_state.json").read_bytes() == original_state
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state == {"completed_urls": [completed_url], "failed_urls": {}}
    assert json.loads(plan_path.read_text(encoding="utf-8"))["removed_urls"] == [failed_url, untracked_url]
    assert replacement.load_replacement_plan(plan_path) == plan


def test_remove_target_urls_deletes_rows_and_prunes_state(tmp_path):
    data_path = tmp_path / "videos.csv"
    state_path = tmp_path / "interaction_backfill_state.json"
    completed_url, failed_url, _untracked_url = write_fixture(data_path, state_path)

    removed_rows = replacement.remove_target_urls(
        [failed_url],
        data_path=data_path,
        state_path=state_path,
    )

    assert removed_rows == 2
    assert load_video_data(data_path)["video_url"].tolist() == [completed_url, _untracked_url]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed_url not in state["failed_urls"]


def test_collect_replacements_removes_failed_new_url_and_keeps_collecting(monkeypatch, tmp_path):
    completed_a = "https://www.bilibili.com/video/BV1completeA"
    completed_b = "https://www.bilibili.com/video/BV1completeB"
    failed_c = "https://www.bilibili.com/video/BV1failedC"
    completed_d = "https://www.bilibili.com/video/BV1completeD"
    plan = replacement.ReplacementPlan(
        data_path=tmp_path / "videos.csv",
        state_path=tmp_path / "state.json",
        backup_dir=tmp_path / "backup",
        plan_path=tmp_path / "plan.json",
        removed_urls=("old-1", "old-2"),
        removed_url_count=2,
        removed_row_count=2,
        initial_completed_count=1,
        target_completed_count=3,
    )
    completed_snapshots = iter(
        [
            {completed_a},
            {completed_a, completed_b},
            {completed_a, completed_b},
            {completed_a, completed_b, completed_d},
        ]
    )
    url_snapshots = iter(
        [
            [completed_a],
            [completed_a, completed_b, failed_c],
            [completed_a, completed_b],
            [completed_a, completed_b, completed_d],
        ]
    )
    crawl_limits = []
    detail_targets = []
    removed_targets = []

    monkeypatch.setattr(replacement, "_completed_urls_in_data", lambda _plan: next(completed_snapshots))
    monkeypatch.setattr(replacement, "get_supported_video_urls", lambda _path: next(url_snapshots))

    def crawl(_keyword, limit):
        crawl_limits.append(limit)
        return {"status": "success", "saved_count": limit, "message": "collection_complete"}

    def details(target_urls, report):
        detail_targets.append(list(target_urls))
        if failed_c in target_urls:
            return {"status": "partial", "updated_count": 1, "remaining_count": 1}
        return {"status": "success", "updated_count": 1, "remaining_count": 0}

    monkeypatch.setattr(replacement, "crawl_bilibili_browser", crawl)
    monkeypatch.setattr(replacement, "run_target_batches", details)
    monkeypatch.setattr(
        replacement,
        "remove_target_urls",
        lambda urls, **_kwargs: removed_targets.append(list(urls)) or len(urls),
    )
    monkeypatch.setattr(replacement, "sleep", lambda _seconds: None)

    result = replacement.collect_replacements(plan, keywords=("Python", "机器学习"))

    assert result["status"] == "success"
    assert crawl_limits == [2, 1]
    assert detail_targets == [[completed_b, failed_c], [completed_d]]
    assert removed_targets == [[failed_c]]


def test_verify_replacement_requires_every_target_url_to_be_completed(tmp_path):
    data_path = tmp_path / "videos.csv"
    state_path = tmp_path / "interaction_backfill_state.json"
    plan_path = tmp_path / "replacement_plan.json"
    completed_url = "https://www.bilibili.com/video/BV1complete"
    pd.DataFrame([video_row(completed_url, "完整视频")], columns=VIDEO_COLUMNS).to_csv(
        data_path,
        index=False,
        encoding="utf-8-sig",
    )
    state_path.write_text(
        json.dumps({"completed_urls": [completed_url], "failed_urls": {}}),
        encoding="utf-8",
    )
    plan = replacement.ReplacementPlan(
        data_path=data_path,
        state_path=state_path,
        backup_dir=tmp_path / "backup",
        plan_path=plan_path,
        removed_urls=("old",),
        removed_url_count=1,
        removed_row_count=1,
        initial_completed_count=0,
        target_completed_count=1,
    )

    summary = replacement.verify_replacement(plan)

    assert summary == {
        "unique_video_count": 1,
        "completed_count": 1,
        "incomplete_count": 0,
        "invalid_metric_count": 0,
        "missing_crawl_date_count": 0,
    }
