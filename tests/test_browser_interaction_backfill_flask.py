from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app import create_app


def create_client(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "interaction-backfill-test-secret",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "CLEANED_DATA_PATH": tmp_path / "videos_cleaned.csv",
            "CLEANING_SUMMARY_PATH": tmp_path / "cleaning_summary.json",
        }
    )
    return app.test_client()


def login(client, username: str, password: str) -> None:
    client.post("/login", data={"username": username, "password": password})


def backfill_result(
    status: str = "success",
    updated_count: int = 50,
    skipped_count: int = 0,
) -> dict[str, object]:
    return {
        "status": status,
        "planned_count": 50,
        "updated_count": updated_count,
        "processed_count": updated_count + skipped_count,
        "skipped_count": skipped_count,
        "failed_count": skipped_count,
        "remaining_count": skipped_count,
        "retryable_count": skipped_count,
        "message": "backfill_complete",
    }


def test_regular_user_cannot_start_interaction_backfill(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")

    response = client.post("/data/browser-backfill")

    assert response.status_code == 403


def test_admin_can_start_interaction_backfill_and_see_summary(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.backfill_bilibili_interactions", return_value=backfill_result()) as backfill:
        response = client.post("/data/browser-backfill", follow_redirects=True)

    page = response.get_data(as_text=True)
    backfill.assert_called_once_with(
        limit=50,
        data_path=tmp_path / "videos.csv",
        state_path=tmp_path / "interaction_backfill_state.json",
    )
    assert "互动数据回填完成" in page
    assert "成功回填：50条" in page


def test_interaction_backfill_reports_verification_and_preserves_summary(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.backfill_bilibili_interactions", return_value=backfill_result("verification_required", updated_count=13)):
        response = client.post("/data/browser-backfill", follow_redirects=True)

    page = response.get_data(as_text=True)
    assert "B站页面需要人工验证" in page
    assert "成功回填：13条" in page


def test_interaction_backfill_reports_partial_batch_and_failure_counts(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch(
        "app.backfill_bilibili_interactions",
        return_value=backfill_result("partial", updated_count=48, skipped_count=2),
    ):
        response = client.post("/data/browser-backfill", follow_redirects=True)

    page = response.get_data(as_text=True)
    assert "互动数据本批部分完成：成功回填48条，跳过2条" in page
    assert "状态：部分完成" in page
    assert "已记录失败：2条" in page


def test_interaction_backfill_reports_occupied_browser_lock(tmp_path):
    from app import browser_crawl_lock

    client = create_client(tmp_path)
    login(client, "admin", "admin123")
    assert browser_crawl_lock.acquire(blocking=False)
    try:
        response = client.post("/data/browser-backfill", follow_redirects=True)
    finally:
        browser_crawl_lock.release()

    assert "浏览器采集任务正在运行，请等待当前任务完成。" in response.get_data(as_text=True)


def test_interaction_backfill_releases_lock_after_browser_failure(tmp_path):
    from app import browser_crawl_lock

    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.backfill_bilibili_interactions", side_effect=RuntimeError("Edge failed")):
        response = client.post("/data/browser-backfill", follow_redirects=True)

    assert response.status_code == 200
    assert browser_crawl_lock.acquire(blocking=False)
    browser_crawl_lock.release()


def test_data_page_has_one_shared_collection_form_and_backfill_control(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.get("/data")

    page = response.get_data(as_text=True)
    assert "浏览器采集（推荐）" in page
    assert "API采集（备用）" in page
    assert "修复历史互动数据（50条）" in page
    assert "无需手动上传 CSV" in page
    assert "自动写入 data/videos.csv" in page
    assert "可选：导入已有 CSV" in page
    assert "先使用上方 B 站采集" in page
    assert page.count('name="keyword"') == 1
    assert page.count('name="limit"') == 1
