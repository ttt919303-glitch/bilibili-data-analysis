from datetime import datetime
import threading

import pytest

from collector.bilibili_collector import CollectorError
from services.hdfs_service import HdfsServiceError


def login_as(client, role):
    with client.session_transaction() as session:
        session.update(user_id=1, username=role, role=role)


def test_normal_user_cannot_call_collect_api(client):
    login_as(client, "user")

    response = client.post(
        "/api/collect",
        json={"keyword": "大数据技术", "date": "2026-08-08", "target_count": 20},
    )

    assert response.status_code == 403


def test_normal_user_cannot_call_clean_api(client):
    login_as(client, "user")

    response = client.post("/api/clean", json={"date": "2026-08-08"})

    assert response.status_code == 403
    assert response.get_json() == {"message": "只有管理员可以执行此操作"}


def test_admin_clean_api_reads_raw_cleans_and_writes_formal(client, monkeypatch):
    login_as(client, "admin")
    raw = [{"bvid": "BV1"}, {"bvid": "BV1"}, {"bvid": "BV2"}]
    cleaned = [{"bvid": "BV1"}, {"bvid": "BV2"}]
    calls = []
    monkeypatch.setattr(
        "app.read_raw_from_hdfs", lambda date: calls.append(("read_raw", date)) or raw
    )
    monkeypatch.setattr(
        "app.clean_video_data", lambda rows: calls.append(("clean", rows)) or cleaned
    )
    monkeypatch.setattr(
        "app.save_to_hdfs", lambda rows, date: calls.append(("save", rows, date)) or 2
    )

    response = client.post("/api/clean", json={"date": "2026-08-08"})

    assert response.status_code == 200
    assert response.get_json() == {
        "before_count": 3,
        "after_count": 2,
        "removed_count": 1,
        "message": "数据清洗完成",
    }
    assert [call[0] for call in calls] == ["read_raw", "clean", "save"]


@pytest.mark.parametrize("value", ["2026-02-30", "20260808", "2026-W32-6"])
def test_clean_api_rejects_invalid_date(client, monkeypatch, value):
    login_as(client, "admin")
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: pytest.fail("invalid dates must not read raw data"),
    )

    response = client.post("/api/clean", json={"date": value})

    assert response.status_code == 400


def test_clean_api_rejects_empty_date_without_reading_raw_data(client, monkeypatch):
    login_as(client, "admin")
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: pytest.fail("empty date must not read raw data"),
    )

    response = client.post("/api/clean", json={"date": ""})

    assert response.status_code == 400


def test_clean_api_does_not_overwrite_formal_data_when_raw_is_missing(client, monkeypatch):
    login_as(client, "admin")
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])
    monkeypatch.setattr(
        "app.save_to_hdfs",
        lambda rows, date: pytest.fail("missing raw data must not overwrite formal data"),
    )

    response = client.post("/api/clean", json={"date": "2026-08-08"})

    assert response.status_code == 404
    assert response.get_json() == {"message": "该日期暂无原始采集数据"}


def test_clean_api_does_not_overwrite_formal_data_when_cleaned_result_is_empty(
    client, monkeypatch
):
    login_as(client, "admin")
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [{"bvid": "BV1"}])
    monkeypatch.setattr("app.clean_video_data", lambda rows: [])
    monkeypatch.setattr(
        "app.save_to_hdfs",
        lambda rows, date: pytest.fail("empty cleaned data must not overwrite formal data"),
    )

    response = client.post("/api/clean", json={"date": "2026-08-08"})

    assert response.status_code == 422
    assert response.get_json() == {"message": "清洗后没有可保存的数据"}


@pytest.mark.parametrize("failed_step", ["read", "clean", "write"])
def test_clean_api_returns_json_and_logs_operational_failures(
    client, monkeypatch, caplog, failed_step
):
    login_as(client, "admin")
    raw = [{"bvid": "BV1"}]

    def fail(message):
        raise RuntimeError(message)

    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: fail("raw read unavailable") if failed_step == "read" else raw,
    )
    monkeypatch.setattr(
        "app.clean_video_data",
        lambda rows: fail("pandas cleaner failed") if failed_step == "clean" else rows,
    )
    monkeypatch.setattr(
        "app.save_to_hdfs",
        lambda rows, date: fail("formal write unavailable")
        if failed_step == "write"
        else len(rows),
    )

    with caplog.at_level("ERROR"):
        response = client.post("/api/clean", json={"date": "2026-08-08"})

    assert response.status_code == 500
    assert response.is_json
    assert response.get_json() == {
        "message": "数据清洗失败，请查看服务日志并检查 HDFS 与数据格式"
    }
    assert "Manual cleaning failed: date=2026-08-08" in caplog.text


def test_collect_api_rejects_invalid_request(client):
    login_as(client, "admin")

    responses = [
        client.post(
            "/api/collect",
            json={"keyword": " ", "date": "2026-08-08", "target_count": 20},
        ),
        client.post(
            "/api/collect",
            json={"keyword": "大数据技术", "date": "2026-02-30", "target_count": 20},
        ),
        client.post(
            "/api/collect",
            json={"keyword": "大数据技术", "date": "2026-08-08", "target_count": 0},
        ),
        client.post(
            "/api/collect",
            json={"keyword": "大数据技术", "date": "2026-08-08", "target_count": 50001},
        ),
    ]

    assert [response.status_code for response in responses] == [400, 400, 400, 400]


def test_collect_api_creates_task_and_starts_daemon_thread(client, monkeypatch):
    login_as(client, "admin")
    started_threads = []

    class ImmediateThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args
            self.daemon = daemon
            started_threads.append(self)

        def start(self):
            return None

    created_tasks = []
    monkeypatch.setattr(
        "app.create_task",
        lambda *args: created_tasks.append(args) or 41,
    )
    monkeypatch.setattr("app.threading.Thread", ImmediateThread)

    response = client.post(
        "/api/collect",
        json={"keyword": " 大数据技术 ", "date": "2026-08-08", "target_count": 20},
    )

    assert response.status_code == 202
    assert response.get_json() == {"task_id": 41}
    assert created_tasks == [("大数据技术", 20, "2026-08-08")]
    assert len(started_threads) == 1
    thread = started_threads[0]
    assert thread.daemon is True
    assert thread.args[1:] == (41, "大数据技术", 20, "2026-08-08")


def test_task_update_rejects_columns_outside_whitelist():
    from app import update_task

    with pytest.raises(ValueError, match="Unsupported task columns"):
        update_task(41, keyword="更换关键字")


def test_collection_page_is_admin_only_and_has_no_upload_control(client, monkeypatch):
    login_as(client, "user")
    assert client.get("/collect").status_code == 403

    login_as(client, "admin")
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])
    response = client.get("/collect")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="collect-form"' in page
    assert page.count("<th>") == 7
    assert 'type="file"' not in page


def test_collection_page_defaults_to_yesterday_and_populates_date(client, monkeypatch):
    login_as(client, "admin")
    monkeypatch.setattr("app.yesterday_string", lambda: "2026-08-08")
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])

    response = client.get("/collect")

    assert response.status_code == 200
    assert 'name="date" type="date" value="2026-08-08"' in response.get_data(
        as_text=True
    )


def test_collection_page_honors_explicit_date(client, monkeypatch):
    login_as(client, "admin")
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])

    response = client.get("/collect?date=2026-08-01")

    assert response.status_code == 200
    assert 'name="date" type="date" value="2026-08-01"' in response.get_data(
        as_text=True
    )


def test_collection_page_explains_success_count_and_links_to_snapshot_data(
    client, monkeypatch
):
    login_as(client, "admin")
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])

    response = client.get("/collect?date=2026-08-01")
    page = response.get_data(as_text=True)

    assert "本次实际新增：" in page
    assert 'id="clean-form"' in page
    assert 'id="clean-date"' in page
    assert "最新原始采集数据" in page
    assert "仅展示该日期最近10条原始数据，完整数据量以上方统计为准" in page
    assert "/data?date=2026-08-01" in page


@pytest.mark.parametrize("value", ["2026-02-30", "20260808", "2026-W32-6"])
def test_collection_page_rejects_invalid_or_noncanonical_date(client, value):
    login_as(client, "admin")

    response = client.get("/collect", query_string={"date": value})

    assert response.status_code == 400


def test_collection_page_counts_unique_raw_bvids_for_selected_date(client, monkeypatch):
    login_as(client, "admin")
    read_dates = []
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: read_dates.append(date)
        or [{"bvid": "BV1"}, {"bvid": "BV1"}, {"bvid": "BV2"}, {"bvid": ""}],
    )

    response = client.get("/collect?date=2026-08-13")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert read_dates == ["2026-08-13"]
    assert 'id="course-target">10000<' in page
    assert 'id="course-current">2<' in page
    assert 'id="course-progress">0.02%<' in page
    assert 'style="width: 0.02%"' in page
    assert "若要持续构建同一课程数据集，请多次采集时选择相同的数据归属日期。" in page


def test_collection_page_shows_unknown_count_when_hdfs_is_unavailable(
    client, monkeypatch
):
    login_as(client, "admin")
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: (_ for _ in ()).throw(HdfsServiceError("offline")),
    )

    response = client.get("/collect?date=2026-08-13")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="course-current">--<' in page
    assert "无法读取数据量，请检查HDFS" in page
    assert 'id="course-current">0<' not in page


def test_collection_page_caps_visual_progress_but_allows_collection_above_target(
    client, monkeypatch
):
    login_as(client, "admin")
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: [{"bvid": f"BV{index}"} for index in range(12000)],
    )

    response = client.get("/collect?date=2026-08-13")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="course-current">12000<' in page
    assert 'id="course-progress">120.00%<' in page
    assert 'style="width: 100.00%"' in page
    assert "已达到课程数据量目标" in page
    assert '<button type="submit">开始采集</button>' in page
    assert '<button type="submit" disabled>' not in page


@pytest.mark.parametrize("value", ["20260808", "2026-W32-6"])
def test_collect_api_rejects_noncanonical_date(client, monkeypatch, value):
    login_as(client, "admin")
    monkeypatch.setattr(
        "app.create_task",
        lambda *args: pytest.fail("invalid dates must not create a task"),
    )

    response = client.post(
        "/api/collect",
        json={"keyword": "大数据技术", "date": value, "target_count": 20},
    )

    assert response.status_code == 400


def test_collection_runner_saves_raw_without_cleaning_or_formal_write(app, monkeypatch):
    raw = [{"bvid": "BV1", "collect_date": "2026-08-08"}]
    calls = []
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: calls.append("read_raw") or ([] if calls.count("read_raw") == 1 else raw),
    )
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: calls.append("collect") or raw)
    monkeypatch.setattr(
        "app.clean_video_data",
        lambda rows: pytest.fail("collection must not clean automatically"),
    )
    monkeypatch.setattr(
        "app.save_to_hdfs",
        lambda rows, date: pytest.fail("collection must not write formal data"),
    )
    monkeypatch.setattr(
        "app.save_raw_to_hdfs", lambda rows, date: calls.append("raw_hdfs") or 1
    )
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: calls.append(values["status"])
    )
    from app import run_collection_task

    run_collection_task(app, 7, "大数据技术", 20, "2026-08-08")

    assert calls == ["running", "read_raw", "collect", "raw_hdfs", "read_raw", "success"]


def test_collection_runner_excludes_raw_bvids_and_stores_added_not_total(
    app, monkeypatch
):
    existing = [{"bvid": f"BV{index:04d}"} for index in range(8000)]
    added = [{"bvid": f"BV{index:04d}"} for index in range(8000, 8300)]
    raw_reads = iter([existing, existing + added])
    collect_calls = []
    updates = []
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: next(raw_reads))
    monkeypatch.setattr(
        "app.collect",
        lambda *args, **kwargs: collect_calls.append((args, kwargs)) or added,
    )
    monkeypatch.setattr("app.save_raw_to_hdfs", lambda rows, date: 300)
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )

    from app import run_collection_task

    run_collection_task(app, 7, "Flink CDC", 500, "2026-08-08")

    assert collect_calls == [
        (
            ("Flink CDC", 500, "2026-08-08"),
            {"exclude_bvids": {row["bvid"] for row in existing}, "task_id": 7},
        )
    ]
    assert updates[-1]["status"] == "success"
    assert updates[-1]["success_count"] == 300
    assert "目标新增500条，实际新增300条" in updates[-1]["message"]


def test_collection_runner_simulates_course_progress_from_8000_to_10000(
    app, monkeypatch
):
    existing = [{"bvid": f"BV{index:05d}"} for index in range(8000)]
    added = [{"bvid": f"BV{index:05d}"} for index in range(8000, 10000)]
    raw_reads = iter([existing, existing + added])
    updates = []
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: next(raw_reads))
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: added)
    monkeypatch.setattr("app.save_raw_to_hdfs", lambda rows, date: 2000)
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )

    from app import run_collection_task

    run_collection_task(app, 13, "课程数据", 2000, "2026-08-13")

    assert updates[-1]["status"] == "success"
    assert updates[-1]["success_count"] == 2000


def test_same_date_tasks_serialize_and_preserve_each_task_start_count(
    app, client, monkeypatch
):
    collect_date = "2026-08-13"
    initial = [{"bvid": f"BV{index:03d}"} for index in range(100)]
    task_a_rows = [{"bvid": f"BVA{index:02d}"} for index in range(10)]
    task_b_rows = [{"bvid": f"BVB{index:02d}"} for index in range(10)]
    raw_records = list(initial)
    raw_lock = threading.Lock()
    task_rows = {1: task_a_rows, 2: task_b_rows}
    tasks = {
        task_id: {
            "id": task_id,
            "keyword": keyword,
            "target_count": 10,
            "success_count": 0,
            "status": "waiting",
            "collect_date": collect_date,
            "message": "",
        }
        for task_id, keyword in ((1, "Spark"), (2, "Hadoop"))
    }
    a_collect_entered = threading.Event()
    release_a = threading.Event()
    b_collect_entered = threading.Event()
    b_exclusions = []
    b_detail_requests = []

    def read_raw(date):
        assert date == collect_date
        with raw_lock:
            return list(raw_records)

    def collect(keyword, target_count, date, *, exclude_bvids, task_id):
        assert target_count == 10
        assert date == collect_date
        if task_id == 1:
            a_collect_entered.set()
            assert release_a.wait(timeout=2)
            return task_rows[task_id]

        b_exclusions.append(set(exclude_bvids))
        b_collect_entered.set()
        candidates = task_a_rows + task_b_rows
        b_detail_requests.extend(
            row["bvid"] for row in candidates if row["bvid"] not in exclude_bvids
        )
        return [row for row in candidates if row["bvid"] not in exclude_bvids]

    def save_raw(rows, date):
        assert date == collect_date
        with raw_lock:
            existing = {row["bvid"] for row in raw_records}
            new_rows = [row for row in rows if row["bvid"] not in existing]
            raw_records.extend(new_rows)
            return len(new_rows)

    def update_task(task_id, **values):
        tasks[task_id].update(values)

    monkeypatch.setattr("app.read_raw_from_hdfs", read_raw)
    monkeypatch.setattr("app.collect", collect)
    monkeypatch.setattr("app.save_raw_to_hdfs", save_raw)
    monkeypatch.setattr("app.update_task", update_task)
    monkeypatch.setattr("app.get_task", lambda task_id: tasks[task_id])

    from app import run_collection_task

    first = threading.Thread(
        target=run_collection_task,
        args=(app, 1, "Spark", 10, collect_date),
    )
    second = threading.Thread(
        target=run_collection_task,
        args=(app, 2, "Hadoop", 10, collect_date),
    )
    first.start()
    assert a_collect_entered.wait(timeout=1)
    second.start()
    second_entered_before_a_finished = b_collect_entered.wait(timeout=0.2)
    second_status_while_a_runs = tasks[2]["status"]
    release_a.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_entered_before_a_finished is False
    assert second_status_while_a_runs == "waiting"
    assert b_exclusions == [
        {row["bvid"] for row in initial + task_a_rows}
    ]
    assert b_detail_requests == [row["bvid"] for row in task_b_rows]
    assert len({row["bvid"] for row in raw_records}) == 120
    assert tasks[1]["success_count"] == 10
    assert tasks[2]["success_count"] == 10

    login_as(client, "user")
    first_status = client.get("/api/collect/status/1").get_json()
    second_status = client.get("/api/collect/status/2").get_json()
    assert {
        key: first_status[key]
        for key in ("existing_count", "added_count", "total_count")
    } == {"existing_count": 100, "added_count": 10, "total_count": 110}
    assert {
        key: second_status[key]
        for key in ("existing_count", "added_count", "total_count")
    } == {"existing_count": 110, "added_count": 10, "total_count": 120}


def test_different_dates_can_collect_at_the_same_time(app, monkeypatch):
    both_collecting = threading.Barrier(2)
    entered = []

    monkeypatch.setattr("app.update_task", lambda task_id, **values: None)
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])

    def collect(keyword, target_count, date, *, exclude_bvids, task_id):
        entered.append(date)
        both_collecting.wait(timeout=1)
        return [{"bvid": f"BV{task_id}"}]

    monkeypatch.setattr("app.collect", collect)
    monkeypatch.setattr("app.save_raw_to_hdfs", lambda rows, date: 1)

    from app import run_collection_task

    threads = [
        threading.Thread(
            target=run_collection_task,
            args=(app, task_id, "Spark", 1, collect_date),
        )
        for task_id, collect_date in ((1, "2026-08-13"), (2, "2026-08-14"))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert set(entered) == {"2026-08-13", "2026-08-14"}


def test_collection_runner_fails_truthfully_when_keyword_adds_no_new_bvids(
    app, monkeypatch
):
    existing = [{"bvid": "BV001"}, {"bvid": "BV001"}, {"bvid": ""}]
    updates = []
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: existing)
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "app.save_raw_to_hdfs",
        lambda rows, date: pytest.fail("zero-new task must not write raw data"),
    )
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )

    from app import run_collection_task

    run_collection_task(app, 9, "Spark", 20, "2026-08-08")

    assert updates[-1]["status"] == "failed"
    assert updates[-1]["success_count"] == 0
    assert updates[-1]["message"] == "该关键词未发现新的唯一视频"


def test_short_collection_is_success_with_actual_count_message(app, monkeypatch):
    raw_reads = iter([[], [{"bvid": "BV1"}]])
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: next(raw_reads))
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: [{"bvid": "BV1"}])
    monkeypatch.setattr("app.save_raw_to_hdfs", lambda rows, date: 1)
    updates = []
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )
    from app import run_collection_task

    run_collection_task(app, 8, "大数据技术", 20, "2026-08-08")

    assert updates[-1]["status"] == "success"
    assert updates[-1]["success_count"] == 1
    assert "目标新增20条，实际新增1条" in updates[-1]["message"]
    assert isinstance(updates[-1]["finished_at"], datetime)


def test_zero_rows_is_failed(app, monkeypatch):
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: [])
    updates = []
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )
    from app import run_collection_task

    run_collection_task(app, 9, "大数据技术", 20, "2026-08-08")

    assert updates[-1]["status"] == "failed"
    assert updates[-1]["success_count"] == 0


def test_zero_hdfs_writes_is_failed(app, monkeypatch):
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: [{"bvid": "BV1"}])
    monkeypatch.setattr("app.save_raw_to_hdfs", lambda rows, date: 0)
    updates = []
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )
    from app import run_collection_task

    run_collection_task(app, 10, "大数据技术", 20, "2026-08-08")

    assert updates[-1]["status"] == "failed"
    assert updates[-1]["success_count"] == 0


def test_collector_failure_stores_safe_message_and_logs_original_error(
    app, monkeypatch, caplog
):
    technical_error = (
        "HTTPSConnectionPool(host='api.bilibili.com'): "
        "https://api.bilibili.com/x/web-interface/search/type "
        "object at 0xABC WinError 10013"
    )
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])
    monkeypatch.setattr(
        "app.collect",
        lambda *args, **kwargs: (_ for _ in ()).throw(CollectorError(technical_error)),
    )
    updates = []
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )
    from app import run_collection_task

    with caplog.at_level("ERROR"):
        run_collection_task(app, 11, "大数据技术", 3, "2026-08-08")

    failure = updates[-1]
    assert failure["status"] == "failed"
    assert failure["success_count"] == 0
    assert failure["message"] == "B站数据采集失败，请检查网络连接或接口状态。"
    assert "HTTPSConnectionPool" not in failure["message"]
    assert "0xABC" not in failure["message"]
    assert "https://" not in failure["message"]
    assert technical_error in caplog.text


def test_hdfs_save_failure_stores_safe_message_and_logs_original_error(
    app, monkeypatch, caplog
):
    technical_error = "HDFS temporary write failed: WinError 10061"
    monkeypatch.setattr("app.read_raw_from_hdfs", lambda date: [])
    monkeypatch.setattr("app.collect", lambda *args, **kwargs: [{"bvid": "BV1"}])
    monkeypatch.setattr(
        "app.save_raw_to_hdfs",
        lambda rows, date: (_ for _ in ()).throw(HdfsServiceError(technical_error)),
    )
    updates = []
    monkeypatch.setattr(
        "app.update_task", lambda task_id, **values: updates.append(values)
    )
    from app import run_collection_task

    with caplog.at_level("ERROR"):
        run_collection_task(app, 12, "大数据技术", 3, "2026-08-08")

    failure = updates[-1]
    assert failure["status"] == "failed"
    assert failure["success_count"] == 0
    assert failure["message"] == "数据保存到 HDFS 失败，请检查 Hadoop/HDFS 是否启动。"
    assert technical_error in caplog.text


def test_success_status_includes_latest_partial_data(client, monkeypatch):
    login_as(client, "user")
    monkeypatch.setattr(
        "app.get_task",
        lambda task_id: {
            "id": task_id,
            "keyword": "大数据技术",
            "target_count": 20,
            "success_count": 1,
            "status": "success",
            "collect_date": "2026-08-08",
            "message": "目标 20 条，实际采集 1 条",
        },
    )
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: [{"bvid": "BV0"}, {"bvid": "BV1", "title": "真实视频"}],
    )
    monkeypatch.setitem(
        __import__("app").TASK_PROGRESS,
        41,
        {"existing_count": 1, "added_count": 1, "total_count": 2},
    )

    response = client.get("/api/collect/status/41")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latest_videos"] == [
        {"bvid": "BV1", "title": "真实视频"},
        {"bvid": "BV0"},
    ]
    assert payload["latest_videos_note"] == "该日期最新原始采集数据（最多10条）"
    assert payload["existing_count"] == 1
    assert payload["added_count"] == 1
    assert payload["total_count"] == 2
    assert payload["course_target"] == 10000


def test_terminal_status_returns_unknown_counts_when_hdfs_is_unavailable(
    client, monkeypatch, caplog
):
    login_as(client, "user")
    monkeypatch.setattr(
        "app.get_task",
        lambda task_id: {
            "id": task_id,
            "keyword": "Spark",
            "target_count": 20,
            "success_count": 0,
            "status": "failed",
            "collect_date": "2026-08-08",
            "message": "数据保存到 HDFS 失败，请检查 Hadoop/HDFS 是否启动。",
        },
    )
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: (_ for _ in ()).throw(HdfsServiceError("offline")),
    )

    with caplog.at_level("ERROR"):
        response = client.get("/api/collect/status/41")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["existing_count"] is None
    assert payload["added_count"] == 0
    assert payload["total_count"] is None
    assert "Collection status HDFS read failed" in caplog.text


def test_terminal_status_without_process_snapshot_does_not_infer_start_count(
    client, monkeypatch
):
    login_as(client, "user")
    monkeypatch.setattr(
        "app.get_task",
        lambda task_id: {
            "id": task_id,
            "keyword": "Spark",
            "target_count": 10,
            "success_count": 10,
            "status": "success",
            "collect_date": "2026-08-13",
            "message": "采集完成",
        },
    )
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: [{"bvid": f"BV{index:03d}"} for index in range(120)],
    )
    monkeypatch.delitem(__import__("app").TASK_PROGRESS, 9001, raising=False)

    response = client.get("/api/collect/status/9001")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["existing_count"] is None
    assert payload["added_count"] == 10
    assert payload["total_count"] == 120


def test_running_status_uses_task_start_snapshot_without_reading_hdfs(
    client, monkeypatch
):
    login_as(client, "user")
    monkeypatch.setattr(
        "app.get_task",
        lambda task_id: {
            "id": task_id,
            "target_count": 500,
            "success_count": 0,
            "status": "running",
            "collect_date": "2026-08-08",
            "message": "",
        },
    )
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: pytest.fail("running status must use its start snapshot"),
    )
    monkeypatch.setitem(
        __import__("app").TASK_PROGRESS,
        41,
        {"existing_count": 8000, "added_count": 0, "total_count": 8000},
    )

    response = client.get("/api/collect/status/41")

    assert response.status_code == 200
    payload = response.get_json()
    assert {
        key: payload[key]
        for key in ("existing_count", "added_count", "total_count", "course_target")
    } == {
        "existing_count": 8000,
        "added_count": 0,
        "total_count": 8000,
        "course_target": 10000,
    }


def test_latest_videos_reads_last_ten_raw_records(monkeypatch):
    monkeypatch.setattr(
        "app.read_raw_from_hdfs",
        lambda date: [{"bvid": f"BV{index}"} for index in range(12)],
    )
    monkeypatch.setattr(
        "app.read_from_hdfs",
        lambda date: pytest.fail("collection status must not read formal data"),
    )
    from app import latest_videos

    videos = latest_videos("2026-08-08")

    assert [video["bvid"] for video in videos] == [
        "BV11",
        "BV10",
        "BV9",
        "BV8",
        "BV7",
        "BV6",
        "BV5",
        "BV4",
        "BV3",
        "BV2",
    ]


def test_pending_status_does_not_read_hdfs(client, monkeypatch):
    login_as(client, "user")
    monkeypatch.setattr(
        "app.get_task",
        lambda task_id: {
            "id": task_id,
            "status": "running",
            "collect_date": "2026-08-08",
        },
    )

    def fail_if_called(date):
        raise AssertionError("running task must not read HDFS")

    monkeypatch.setattr("app.latest_videos", fail_if_called)

    response = client.get("/api/collect/status/41")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latest_videos"] == []
    assert payload["existing_count"] is None
    assert payload["added_count"] == 0
    assert payload["total_count"] is None
