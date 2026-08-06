from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app import create_app
from browser_crawler import BrowserCrawlerError


def create_client(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "browser-crawl-test-secret",
            "DATABASE": tmp_path / "users.db",
            "VIDEO_DATA_PATH": tmp_path / "videos.csv",
            "CLEANED_DATA_PATH": tmp_path / "videos_cleaned.csv",
            "CLEANING_SUMMARY_PATH": tmp_path / "cleaning_summary.json",
        }
    )
    return app.test_client()


def login(client, username: str, password: str) -> None:
    client.post("/login", data={"username": username, "password": password})


def browser_result(status: str = "success", saved_count: int = 20) -> dict[str, object]:
    return {
        "status": status,
        "keyword": "Python",
        "planned_count": 20,
        "collected_count": saved_count,
        "parsed_count": 24,
        "skipped_count": 4,
        "page_count": 1,
        "saved_count": saved_count,
        "message": "collection_complete",
    }


def interaction_result(
    status: str = "success",
    updated_count: int = 20,
    remaining_count: int = 0,
) -> dict[str, object]:
    return {
        "status": status,
        "batch_count": 1,
        "updated_count": updated_count,
        "processed_count": updated_count,
        "skipped_count": 0,
        "failed_count": remaining_count,
        "remaining_count": remaining_count,
    }


@pytest.fixture(autouse=True)
def complete_interaction_collection():
    with patch("app.get_supported_video_urls", side_effect=[[], ["https://www.bilibili.com/video/BV1new"]]), patch(
        "app.run_target_batches",
        return_value=interaction_result(),
    ):
        yield


def test_regular_user_cannot_start_browser_crawl(tmp_path):
    client = create_client(tmp_path)
    login(client, "user", "user123")

    response = client.post("/data/browser-crawl", data={"keyword": "Python", "limit": "20"})

    assert response.status_code == 403


def test_admin_can_start_browser_crawl(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result()) as crawl:
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    crawl.assert_called_once_with("Python", 20)


def test_browser_crawl_rejects_blank_keyword(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.post("/data/browser-crawl", data={"keyword": "   ", "limit": "20"}, follow_redirects=True)

    assert "请输入采集关键词。" in response.get_data(as_text=True)


@pytest.mark.parametrize("limit", ("0", "201"))
def test_browser_crawl_rejects_limit_outside_browser_range(tmp_path, limit):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.post("/data/browser-crawl", data={"keyword": "Python", "limit": limit}, follow_redirects=True)

    assert "浏览器采集数量必须为1~200之间的整数。" in response.get_data(as_text=True)


def test_browser_crawl_success_shows_saved_summary(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result()):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    page = response.get_data(as_text=True)
    assert "浏览器采集完成" in page
    assert "实际新增：20条" in page
    assert "解析视频：24条" in page
    assert "跳过重复：4条" in page


def test_browser_crawl_reports_automatic_detail_interaction_collection(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result()), patch(
        "app.run_target_batches",
        return_value=interaction_result(updated_count=20),
    ):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    assert "详情互动采集：20条" in response.get_data(as_text=True)


def test_browser_crawl_collects_details_only_for_urls_added_by_this_request(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")
    existing_url = "https://www.bilibili.com/video/BV1existing"
    new_url = "https://www.bilibili.com/video/BV1new"

    with patch("app.crawl_bilibili_browser", return_value=browser_result(saved_count=1)), patch(
        "app.get_supported_video_urls",
        side_effect=[[existing_url], [existing_url, new_url]],
        create=True,
    ), patch(
        "app.run_target_batches",
        return_value=interaction_result(updated_count=1),
        create=True,
    ) as detail_collection:
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "1"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert detail_collection.call_args.args[0] == [new_url]


def test_browser_crawl_does_not_report_success_when_detail_page_requires_verification(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result()), patch(
        "app.run_target_batches",
        return_value=interaction_result(
            "verification_required",
            updated_count=13,
            remaining_count=7,
        ),
    ):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    page = response.get_data(as_text=True)
    assert "详情互动数据采集需要人工验证" in page
    assert "浏览器采集完成：成功新增 20 条视频数据。" not in page


def test_browser_crawl_partial_result_preserves_saved_count(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result("partial", saved_count=13)):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    page = response.get_data(as_text=True)
    assert "计划采集20条，本次成功新增13条。" in page
    assert "实际新增：13条" in page


def test_browser_crawl_verification_result_shows_manual_action(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result("verification_required", saved_count=13)):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    assert "B站页面需要人工验证，本次已成功采集的数据已经保存，请完成验证后再继续。" in response.get_data(as_text=True)


def test_browser_crawl_page_structure_error_is_not_reported_as_no_results(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", return_value=browser_result("page_structure_error", saved_count=0)):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    page = response.get_data(as_text=True)
    assert "暂时无法识别B站搜索页面结构，请稍后检查页面。" in page
    assert "未找到与“Python”相关的视频" not in page


def test_browser_start_failure_shows_friendly_message(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", side_effect=BrowserCrawlerError("Edge failed")):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "浏览器采集无法启动，请确认Microsoft Edge未被项目其他采集任务占用。" in response.get_data(as_text=True)


def test_browser_crawl_reports_an_occupied_lock(tmp_path):
    from app import browser_crawl_lock

    client = create_client(tmp_path)
    login(client, "admin", "admin123")
    assert browser_crawl_lock.acquire(blocking=False)
    try:
        response = client.post("/data/browser-crawl", data={"keyword": "Python", "limit": "20"}, follow_redirects=True)
    finally:
        browser_crawl_lock.release()

    assert "浏览器采集任务正在运行，请等待当前任务完成。" in response.get_data(as_text=True)


def test_browser_crawl_releases_lock_after_unexpected_exception(tmp_path):
    from app import browser_crawl_lock

    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili_browser", side_effect=RuntimeError("unexpected")):
        response = client.post(
            "/data/browser-crawl",
            data={"keyword": "Python", "limit": "20"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "浏览器采集无法启动，请确认Microsoft Edge未被项目其他采集任务占用。" in response.get_data(as_text=True)
    assert browser_crawl_lock.acquire(blocking=False)
    browser_crawl_lock.release()


def test_api_crawl_route_remains_available(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    with patch("app.crawl_bilibili", return_value=pd.DataFrame()):
        response = client.post("/data/crawl", data={"keyword": "Python", "limit": "1"}, follow_redirects=True)

    assert response.status_code == 200


def test_data_page_shows_browser_and_api_collection_choices(tmp_path):
    client = create_client(tmp_path)
    login(client, "admin", "admin123")

    response = client.get("/data")

    page = response.get_data(as_text=True)
    assert "浏览器采集（推荐）" in page
    assert "API采集（备用）" in page
