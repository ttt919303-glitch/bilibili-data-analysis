import pytest
import requests

from collector import bilibili_collector as collector


EXPECTED_FIELDS = {
    "bvid", "title", "video_url", "up_name", "publish_time",
    "view_count", "like_count", "coin_count", "favorite_count",
    "share_count", "collect_date",
}


def test_get_video_detail_maps_public_view_fields(monkeypatch):
    request = {}
    payload = {
        "code": 0,
        "data": {
            "bvid": "BV1TEST",
            "title": "Spark 入门",
            "pubdate": 1723075200,
            "owner": {"name": "课程UP"},
            "stat": {
                "view": 1200, "like": 80, "coin": 20,
                "favorite": 30, "share": 10, "reply": 999,
            },
        },
    }
    def request_json(url, params):
        request.update(url=url, params=params)
        return payload

    monkeypatch.setattr(collector, "_request_json", request_json)
    result = collector.get_video_detail("BV1TEST")
    assert request == {
        "url": "https://api.bilibili.com/x/web-interface/view",
        "params": {"bvid": "BV1TEST"},
    }
    assert set(result) == EXPECTED_FIELDS - {"collect_date"}
    assert result["view_count"] == 1200
    assert result["like_count"] == 80
    assert "comment_count" not in result
    assert "comments" not in result


def test_collect_adds_snapshot_date_without_filtering_publish_time(monkeypatch):
    monkeypatch.setattr(
        collector,
        "search_videos",
        lambda keyword, page: collector.SearchPage(["BV1TEST"], 1),
    )
    monkeypatch.setattr(
        collector,
        "get_video_detail",
        lambda bvid: {
            "bvid": bvid, "title": "旧视频", "video_url": "https://www.bilibili.com/video/BV1TEST",
            "up_name": "课程UP", "publish_time": "2024-01-01 08:00:00",
            "view_count": 1, "like_count": 2, "coin_count": 3,
            "favorite_count": 4, "share_count": 5,
        },
    )
    result = collector.collect("大数据技术", 1, "2026-08-08")
    assert result[0]["collect_date"] == "2026-08-08"
    assert result[0]["publish_time"] == "2024-01-01 08:00:00"


def test_clean_video_data_converts_units_and_deduplicates_bvid():
    rows = [
        {"bvid": "BV1", "title": "A", "video_url": "u", "up_name": "UP",
         "publish_time": "2026-08-01", "view_count": "1.1万", "like_count": "2万",
         "coin_count": None, "favorite_count": 3, "share_count": "4",
         "collect_date": "2026/08/08"},
        {"bvid": "BV1", "title": "A2", "video_url": "u2", "up_name": "UP",
         "publish_time": "2026-08-02", "view_count": 12000, "like_count": 5,
         "coin_count": 6, "favorite_count": 7, "share_count": 8,
         "collect_date": "2026-08-08"},
    ]
    result = collector.clean_video_data(rows)
    assert len(result) == 1
    assert result[0]["title"] == "A2"
    assert result[0]["view_count"] == 12000
    assert result[0]["collect_date"] == "2026-08-08"
    assert set(result[0]) == EXPECTED_FIELDS


@pytest.mark.parametrize("page", [1, 2])
def test_search_videos_uses_wbi_path_and_passes_page(monkeypatch, page):
    request = {}

    def request_json(url, params):
        request.update(url=url, params=params)
        return {
            "code": 0,
            "data": {
                "numPages": 50,
                "result": [
                    {"bvid": "BV1FIRST"}, {"bvid": ""},
                    {"bvid": "BV1FIRST"}, {"bvid": "BV1SECOND"},
                ],
            },
        }

    monkeypatch.setattr(
        collector,
        "_request_json",
        request_json,
    )
    assert collector.search_videos("大数据技术", page) == collector.SearchPage(
        ["BV1FIRST", "BV1SECOND"], 50
    )
    assert request == {
        "url": "https://api.bilibili.com/x/web-interface/wbi/search/type",
        "params": {"search_type": "video", "keyword": "大数据技术", "page": page},
    }


def test_collector_session_has_no_explicit_proxy_by_default(monkeypatch):
    monkeypatch.delenv("BILIBILI_PROXY", raising=False)

    session = collector._create_session()

    assert session.proxies == {}


def test_collector_session_applies_bilibili_proxy_locally(monkeypatch):
    monkeypatch.setenv("BILIBILI_PROXY", "http://127.0.0.1:7890")

    session = collector._create_session()

    assert session.proxies == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    assert requests.Session().proxies == {}


def test_search_response_extracts_bvids_from_wbi_shape(monkeypatch):
    results = [{"bvid": f"BV{index:02d}"} for index in range(20)]
    monkeypatch.setattr(
        collector,
        "_request_json",
        lambda url, params: {
            "code": 0,
            "message": "OK",
            "data": {"page": 1, "numPages": 1, "result": results},
        },
    )

    assert collector.search_videos("data", 1) == collector.SearchPage(
        [f"BV{index:02d}" for index in range(20)], 1
    )


def test_search_empty_result_is_normal_exhaustion_even_when_num_pages_is_zero(
    monkeypatch,
):
    monkeypatch.setattr(
        collector,
        "_request_json",
        lambda url, params: {
            "code": 0,
            "message": "OK",
            "data": {"page": 1, "numPages": 0, "result": []},
        },
    )

    assert collector.search_videos("no result", 1) == collector.SearchPage([], 1)


def test_request_json_rejects_nonzero_business_code(monkeypatch):
    class Response:
        status_code = 200
        text = '{"code": -352, "message": "risk control"}'

        @staticmethod
        def json():
            return {"code": -352, "message": "risk control"}

    monkeypatch.setattr(collector.SESSION, "get", lambda *args, **kwargs: Response())

    with pytest.raises(collector.CollectorError, match="business_code=-352"):
        collector._request_json(collector.SEARCH_URL, {"page": 1})


def test_request_json_rejects_http_412(monkeypatch):
    class Response:
        status_code = 412
        text = "precondition failed"

    monkeypatch.setattr(collector.SESSION, "get", lambda *args, **kwargs: Response())

    with pytest.raises(collector.CollectorError, match="http_status=412"):
        collector._request_json(collector.SEARCH_URL, {"page": 1})


def _video(bvid):
    return {
        "bvid": bvid,
        "title": bvid,
        "video_url": f"https://www.bilibili.com/video/{bvid}",
        "up_name": "UP",
        "publish_time": "2026-08-08 00:00:00",
        "view_count": 1,
        "like_count": 2,
        "coin_count": 3,
        "favorite_count": 4,
        "share_count": 5,
    }


@pytest.mark.parametrize(
    ("target_count", "expected_pages"),
    [(21, [1, 2]), (50, [1, 2, 3])],
)
def test_collect_reaches_target_across_pages(
    monkeypatch, target_count, expected_pages
):
    requested_pages = []

    def search_videos(keyword, page):
        requested_pages.append(page)
        start = (page - 1) * 20
        return collector.SearchPage(
            [f"BV{index:03d}" for index in range(start, start + 20)],
            3,
        )

    monkeypatch.setattr(collector, "search_videos", search_videos)
    monkeypatch.setattr(collector, "get_video_detail", _video)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    result = collector.collect("data", target_count, "2026-08-08")

    assert len(result) == target_count
    assert requested_pages == expected_pages


def test_collect_does_not_count_duplicate_bvids_toward_target(monkeypatch):
    requested_pages = []

    def search_videos(keyword, page):
        requested_pages.append(page)
        if page == 1:
            return collector.SearchPage([f"BV{index:03d}" for index in range(20)], 2)
        return collector.SearchPage(["BV000", "BV020"], 2)

    monkeypatch.setattr(collector, "search_videos", search_videos)
    monkeypatch.setattr(collector, "get_video_detail", _video)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    result = collector.collect("data", 21, "2026-08-08")

    assert len(result) == 21
    assert len({row["bvid"] for row in result}) == 21
    assert requested_pages == [1, 2]


def test_collect_continues_after_one_detail_failure(monkeypatch):
    monkeypatch.setattr(
        collector,
        "search_videos",
        lambda keyword, page: collector.SearchPage(["BV1BAD", "BV1GOOD"], 1),
    )

    def get_video_detail(bvid):
        if bvid == "BV1BAD":
            raise collector.CollectorError("detail unavailable")
        return {
            "bvid": bvid, "title": "正常视频", "video_url": "https://www.bilibili.com/video/BV1GOOD",
            "up_name": "课程UP", "publish_time": "2026-08-08 00:00:00",
            "view_count": 1, "like_count": 2, "coin_count": 3,
            "favorite_count": 4, "share_count": 5,
        }

    monkeypatch.setattr(collector, "get_video_detail", get_video_detail)
    assert [row["bvid"] for row in collector.collect("大数据技术", 1, "2026-08-08")] == ["BV1GOOD"]


def test_collect_skips_historical_bvids_before_requesting_detail(monkeypatch):
    detail_requests = []
    monkeypatch.setattr(
        collector,
        "search_videos",
        lambda keyword, page: collector.SearchPage(["BV001", "BV002", "BV003"], 1),
    )
    monkeypatch.setattr(
        collector,
        "get_video_detail",
        lambda bvid: detail_requests.append(bvid) or _video(bvid),
    )

    result = collector.collect(
        "Spark",
        20,
        "2026-08-08",
        exclude_bvids={"BV001", "BV002"},
    )

    assert [row["bvid"] for row in result] == ["BV003"]
    assert detail_requests == ["BV003"]


def test_collect_continues_after_a_page_contains_only_historical_bvids(monkeypatch):
    requested_pages = []

    def search_videos(keyword, page):
        requested_pages.append(page)
        if page == 1:
            return collector.SearchPage([f"BV{index:03d}" for index in range(20)], 2)
        return collector.SearchPage(["BVNEW"], 2)

    monkeypatch.setattr(collector, "search_videos", search_videos)
    monkeypatch.setattr(collector, "get_video_detail", _video)

    result = collector.collect(
        "Spark",
        1,
        "2026-08-08",
        exclude_bvids={f"BV{index:03d}" for index in range(20)},
    )

    assert [row["bvid"] for row in result] == ["BVNEW"]
    assert requested_pages == [1, 2]


def test_collect_logs_scanned_pages_when_all_results_are_historical(
    monkeypatch, caplog
):
    monkeypatch.setattr(
        collector,
        "search_videos",
        lambda keyword, page: collector.SearchPage([f"BV{page}"], 2),
    )
    monkeypatch.setattr(
        collector,
        "get_video_detail",
        lambda bvid: pytest.fail("historical BV must not request detail"),
    )

    with caplog.at_level("INFO"):
        result = collector.collect(
            "Spark",
            20,
            "2026-08-08",
            exclude_bvids={"BV1", "BV2"},
            task_id=7,
        )

    assert result == []
    assert "task_id=7 keyword=Spark pages_scanned=2 new_bvid_count=0" in caplog.text


def test_collect_returns_actual_count_when_search_results_are_exhausted(monkeypatch):
    requested_pages = []

    def search_videos(keyword, page):
        requested_pages.append(page)
        start = (page - 1) * 109
        return collector.SearchPage(
            [f"BV{index:03d}" for index in range(start, min(start + 109, 327))],
            3,
        )

    monkeypatch.setattr(collector, "search_videos", search_videos)
    monkeypatch.setattr(collector, "get_video_detail", _video)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    result = collector.collect("Spark", 500, "2026-08-08")

    assert len(result) == 327
    assert requested_pages == [1, 2, 3]


def test_collect_requests_details_only_for_300_new_bvids_across_all_pages(monkeypatch):
    detail_requests = []
    all_bvids = [f"BV{index:04d}" for index in range(1000)]

    def search_videos(keyword, page):
        start = (page - 1) * 20
        return collector.SearchPage(all_bvids[start : start + 20], 50)

    monkeypatch.setattr(collector, "search_videos", search_videos)
    monkeypatch.setattr(
        collector,
        "get_video_detail",
        lambda bvid: detail_requests.append(bvid) or _video(bvid),
    )
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    result = collector.collect(
        "Spark",
        500,
        "2026-08-08",
        exclude_bvids=set(all_bvids[:700]),
    )

    assert len(result) == 300
    assert detail_requests == all_bvids[700:]


def test_collect_passes_custom_keyword_unchanged_to_every_search_page(monkeypatch):
    search_calls = []

    def search_videos(keyword, page):
        search_calls.append((keyword, page))
        return collector.SearchPage([f"BV{page}"], 2)

    monkeypatch.setattr(collector, "search_videos", search_videos)
    monkeypatch.setattr(collector, "get_video_detail", _video)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)

    result = collector.collect("Flink CDC", 20, "2026-08-08")

    assert len(result) == 2
    assert search_calls == [("Flink CDC", 1), ("Flink CDC", 2)]


def test_clean_video_data_drops_blank_bvid_and_clamps_invalid_statistics():
    row = {
        "bvid": "", "title": "删除", "video_url": "u", "up_name": "UP",
        "publish_time": "2026-08-08", "view_count": -1, "like_count": None,
        "coin_count": "bad", "favorite_count": "-3", "share_count": "1.9万",
        "collect_date": "2026-08-08",
    }
    valid_row = {**row, "bvid": "BV1VALID"}
    result = collector.clean_video_data([row, valid_row])
    assert result == [{
        "bvid": "BV1VALID", "title": "删除", "video_url": "u", "up_name": "UP",
        "publish_time": "2026-08-08 00:00:00", "view_count": 0, "like_count": 0,
        "coin_count": 0, "favorite_count": 0, "share_count": 19000,
        "collect_date": "2026-08-08",
    }]
