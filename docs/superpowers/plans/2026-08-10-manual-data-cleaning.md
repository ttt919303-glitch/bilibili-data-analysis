# Manual Data Cleaning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate Bilibili collection from pandas cleaning so collection writes cumulative raw HDFS data and only an administrator-triggered API updates the existing cleaned dataset.

**Architecture:** Keep the single Flask process and existing collection thread. Add raw-path wrappers to the current HDFS service, switch collection/status reads to those wrappers, and add one synchronous administrator-only cleaning endpoint that uses the existing `clean_video_data()` and formal HDFS writer; all downstream pages retain `read_from_hdfs()`.

**Tech Stack:** Python 3.8+, Flask, pandas, WebHDFS `hdfs.InsecureClient`, Jinja2, browser JavaScript, pytest, Node.js test runner.

## Global Constraints

- Raw path is `/bigdata_course/bilibili/date=YYYY-MM-DD/videos_raw.jsonl`; formal path remains `/bigdata_course/bilibili/date=YYYY-MM-DD/videos.jsonl`.
- Collection and scheduled collection must not call `clean_video_data()` or write formal `videos.jsonl`.
- Only `POST /api/clean` may turn raw records into formal records, and only administrators may call it.
- Raw and formal records retain exactly the frozen 11 fields; never add comments, `comment_count`, `stat.reply`, or CSV upload/download flow.
- `/`, `/data`, `/mining`, Spark analysis, `/visualization`, and `/knowledge` continue to use `read_from_hdfs()`.
- Do not add database tables, background clean jobs, Celery, Redis, Docker, microservices, or new architecture layers.
- Existing formal HDFS data must not be deleted, migrated, or overwritten by an empty clean result.
- Do not modify `collector.collect()` or the mining, Spark, knowledge, authentication, and scheduler architectures.

---

### Task 1: Add raw HDFS read/write operations

**Files:**
- Modify: `services/hdfs_service.py`
- Test: `tests/test_hdfs_service.py`

**Interfaces:**
- Consumes: existing `video_path(date)`, `_read_records(client, date, path)`, `_lock_for_date(date)`, and `InsecureClient` exchange behavior.
- Produces: `raw_video_path(date: str) -> str`, `save_raw_to_hdfs(data: List[Dict], date: str) -> int`, and `read_raw_from_hdfs(date: str) -> List[Dict]`.

- [ ] **Step 1: Write failing raw-path and cumulative-save tests**

Append tests that prove raw and formal paths are independent and raw writes keep the last duplicate BV record:

```python
def test_raw_path_is_separate_from_formal_path():
    date = "2026-08-08"
    assert hdfs_service.raw_video_path(date).endswith("/videos_raw.jsonl")
    assert hdfs_service.raw_video_path(date) != hdfs_service.video_path(date)


def test_raw_save_merges_by_bvid_and_does_not_change_formal_file(monkeypatch):
    date = "2026-08-08"
    raw_path = hdfs_service.raw_video_path(date)
    formal_path = hdfs_service.video_path(date)
    formal_content = json.dumps(row("BVCLEAN", "cleaned"), ensure_ascii=False) + "\n"
    client = FakeHdfsClient(
        {
            formal_path: formal_content,
            raw_path: json.dumps(row("BV1", "old"), ensure_ascii=False) + "\n",
        }
    )
    monkeypatch.setattr(hdfs_service, "_client", lambda: client)

    count = hdfs_service.save_raw_to_hdfs(
        [row("BV1", "new"), row("BV2", "second")], date
    )

    saved = [json.loads(line) for line in client.files[raw_path].splitlines()]
    assert count == 2
    assert [(item["bvid"], item["title"]) for item in saved] == [
        ("BV1", "new"),
        ("BV2", "second"),
    ]
    assert client.files[formal_path] == formal_content
    assert hdfs_service.read_raw_from_hdfs(date) == saved
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_hdfs_service.py -k "raw_path or raw_save"
```

Expected: FAIL because `raw_video_path`, `save_raw_to_hdfs`, and `read_raw_from_hdfs` do not exist.

- [ ] **Step 3: Implement shared internal path-based helpers and raw wrappers**

Keep the public formal API unchanged. Refactor only enough to let both paths use the same safe exchange logic:

```python
def raw_video_path(date: str) -> str:
    return f"{BASE_PATH}/date={date}/videos_raw.jsonl"


def _read_from_path(date: str, path: str) -> List[Dict]:
    with _lock_for_date(date):
        try:
            client = _client()
        except Exception as exc:
            raise _hdfs_error("connect", date, path, exc) from exc
        return _read_records(client, date, path)


def read_from_hdfs(date: str) -> List[Dict]:
    return _read_from_path(date, video_path(date))


def read_raw_from_hdfs(date: str) -> List[Dict]:
    return _read_from_path(date, raw_video_path(date))
```

Move the existing merge/temp-write/backup/exchange body into `_save_to_path(data, date, path)` without changing its behavior, then delegate:

```python
def save_to_hdfs(data: List[Dict], date: str) -> int:
    return _save_to_path(data, date, video_path(date))


def save_raw_to_hdfs(data: List[Dict], date: str) -> int:
    return _save_to_path(data, date, raw_video_path(date))
```

The private `_save_to_path` must keep the existing empty-input rejection, date lock, incoming `bvid` dictionary, `collect_date=date`, unique temporary/backup names, recovery behavior, and cleanup logging.

- [ ] **Step 4: Run HDFS service tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_hdfs_service.py
```

Expected: all HDFS tests PASS, including the existing formal-file exchange and lock tests.

- [ ] **Step 5: Commit Task 1**

```powershell
git add services/hdfs_service.py tests/test_hdfs_service.py
git commit -m "feat: add raw HDFS video storage"
```

---

### Task 2: Make collection write and display raw data only

**Files:**
- Modify: `app.py`
- Test: `tests/test_collection_flow.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `collect(keyword, target_count, collect_date)`, `save_raw_to_hdfs(data, date)`, `read_raw_from_hdfs(date)`, existing MySQL task updates.
- Produces: `run_collection_task()` with no automatic cleaning/formal write and `latest_videos()` backed only by raw data.

- [ ] **Step 1: Replace old auto-clean expectations with failing separation tests**

Change the collection runner test so any automatic clean or formal write fails immediately:

```python
def test_collection_runner_saves_raw_without_cleaning_or_formal_write(app, monkeypatch):
    raw = [{"bvid": "BV1", "collect_date": "2026-08-08"}]
    calls = []
    monkeypatch.setattr("app.collect", lambda *args: calls.append("collect") or raw)
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

    assert calls == ["running", "collect", "raw_hdfs", "success"]
```

Update short/zero-write tests to patch `save_raw_to_hdfs` rather than the formal writer. Change the latest-video source test to patch `app.read_raw_from_hdfs`; make `app.read_from_hdfs` fail if called:

```python
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
    assert [item["bvid"] for item in latest_videos("2026-08-08")] == [
        "BV11", "BV10", "BV9", "BV8", "BV7",
        "BV6", "BV5", "BV4", "BV3", "BV2",
    ]
```

Add a scheduler assertion that `run_scheduled_collection()` still delegates to `run_collection_task()` and never calls `clean_video_data()` directly.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_collection_flow.py tests/test_scheduler.py
```

Expected: FAIL because collection still calls `clean_video_data()` and `save_to_hdfs()`, and latest videos still read formal data.

- [ ] **Step 3: Switch collection orchestration to raw storage**

Import raw functions while keeping formal imports for downstream pages and the later clean API:

```python
from services.hdfs_service import (
    read_from_hdfs,
    read_raw_from_hdfs,
    save_raw_to_hdfs,
    save_to_hdfs,
)
```

Change only these two flows:

```python
def latest_videos(collect_date: str, limit: int = 10) -> list:
    return list(reversed(read_raw_from_hdfs(collect_date)))[:limit]
```

Inside `run_collection_task()`:

```python
raw_videos = collect(keyword, target_count, collect_date)
if not raw_videos:
    raise RuntimeError("采集结果为空")

saved_count = save_raw_to_hdfs(raw_videos, collect_date)
if saved_count < 1:
    raise RuntimeError("HDFS 未写入任何原始视频数据")
```

Remove the automatic `clean_video_data(raw_videos)` call and its cleaned-count log. Update logging text to state raw counts/paths without changing task status rules.

Update the successful status note to `该日期最新原始采集数据（最多10条）`.

- [ ] **Step 4: Run collection and scheduler tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_collection_flow.py tests/test_scheduler.py
```

Expected: all focused tests PASS; no collector implementation changes.

- [ ] **Step 5: Commit Task 2**

```powershell
git add app.py tests/test_collection_flow.py tests/test_scheduler.py
git commit -m "fix: separate collection from data cleaning"
```

---

### Task 3: Add administrator-only synchronous cleaning API

**Files:**
- Modify: `app.py`
- Modify: `tests/test_collection_flow.py`
- Modify: `tests/test_project_contract.py`

**Interfaces:**
- Consumes: `read_raw_from_hdfs(date)`, existing `clean_video_data(records)`, `save_to_hdfs(records, date)`, `selected_date(value)`, `login_required`, and `admin_required`.
- Produces: `POST /api/clean` JSON response with integer `before_count`, `after_count`, `removed_count`, and string `message`.

- [ ] **Step 1: Write failing authorization and successful-clean tests**

Add the route to the required route contract and add API tests:

```python
def test_normal_user_cannot_call_clean_api(client):
    login_as(client, "user")
    response = client.post("/api/clean", json={"date": "2026-08-08"})
    assert response.status_code == 403


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
```

Add invalid-date, missing-raw, and empty-clean-result tests. The latter two must patch `save_to_hdfs` with `pytest.fail(...)` to prove formal data is not overwritten.

- [ ] **Step 2: Run focused API tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_collection_flow.py -k "clean_api"
python -m pytest -q tests/test_project_contract.py::test_required_routes_exist
```

Expected: FAIL with 404 for the missing `/api/clean` route.

- [ ] **Step 3: Implement the minimal synchronous endpoint**

Add inside `create_app()`:

```python
@app.post("/api/clean")
@login_required
@admin_required
def clean_data():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("date"), str):
        return {"message": "日期必须为 YYYY-MM-DD 格式"}, 400
    try:
        clean_date = selected_date(payload["date"])
    except ValueError as exc:
        return {"message": str(exc)}, 400

    raw_records = read_raw_from_hdfs(clean_date)
    if not raw_records:
        return {"message": "该日期暂无原始采集数据"}, 404

    cleaned_records = clean_video_data(raw_records)
    if not cleaned_records:
        return {"message": "清洗后没有可保存的数据"}, 422

    save_to_hdfs(cleaned_records, clean_date)
    before_count = len(raw_records)
    after_count = len(cleaned_records)
    current_app.logger.info(
        "Manual cleaning completed: date=%s, before_count=%s, after_count=%s",
        clean_date,
        before_count,
        after_count,
    )
    return {
        "before_count": before_count,
        "after_count": after_count,
        "removed_count": before_count - after_count,
        "message": "数据清洗完成",
    }
```

Do not create a cleaning task table or thread. Let existing HDFS service exceptions remain observable through Flask logging; do not return a false success response.

- [ ] **Step 4: Run API and contract tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_collection_flow.py tests/test_project_contract.py
```

Expected: all focused tests PASS, including normal-user 403 and no-overwrite cases.

- [ ] **Step 5: Commit Task 3**

```powershell
git add app.py tests/test_collection_flow.py tests/test_project_contract.py
git commit -m "feat: add manual data cleaning endpoint"
```

---

### Task 4: Add the cleaning controls and update course documentation

**Files:**
- Modify: `templates/collect.html`
- Modify: `static/js/main.js`
- Modify: `tests/test_collection_flow.py`
- Modify: `tests/test_main_polling.js`
- Modify: `README.md`

**Interfaces:**
- Consumes: `POST /api/clean`, existing selected date template value, collection status `latest_videos` raw records.
- Produces: `clean-form` UI, synchronous clean result rendering, raw-table wording, and current-date `/data` link.

- [ ] **Step 1: Write failing template and browser behavior tests**

Update the collection page test to assert:

```python
assert 'id="clean-form"' in page
assert 'id="clean-date"' in page
assert "最新原始采集数据" in page
assert "仅展示该日期最近10条，尚未经过手动数据清洗" in page
assert "/data?date=2026-08-01" in page
```

Extend `FakeElement` with `disabled = false`, register `clean-form`, `clean-date`, `clean-status`, `clean-before`, `clean-after`, `clean-removed`, and `clean-message`, then add a Node test:

```javascript
test("manual cleaning posts the date and renders returned counts", async () => {
    const requests = [];
    const page = loadCollectionPage(async (url, options) => {
        requests.push({url, options});
        return jsonResponse(200, {
            before_count: 100,
            after_count: 96,
            removed_count: 4,
            message: "数据清洗完成",
        });
    });

    await page.clean();

    assert.equal(requests[0].url, "/api/clean");
    assert.deepEqual(JSON.parse(requests[0].options.body), {date: "2026-08-09"});
    assert.equal(page.elements.get("clean-status").textContent, "清洗完成");
    assert.equal(page.elements.get("clean-before").textContent, "100");
    assert.equal(page.elements.get("clean-after").textContent, "96");
    assert.equal(page.elements.get("clean-removed").textContent, "4");
});
```

- [ ] **Step 2: Run focused UI tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_collection_flow.py -k "collection_page"
node tests/test_main_polling.js
```

Expected: template test FAIL because the cleaning form/raw wording is absent; Node test FAIL because no clean submission handler exists.

- [ ] **Step 3: Add the minimal Jinja cleaning region**

Add a card below collection task information:

```html
<section class="card" aria-live="polite">
    <h2>数据清洗</h2>
    <form id="clean-form">
        <label for="clean-date">清洗日期</label>
        <input id="clean-date" name="date" type="date" value="{{ selected_date }}" required>
        <button type="submit">开始数据清洗</button>
    </form>
    <p>清洗前：<span id="clean-before">--</span> 条</p>
    <p>清洗后：<span id="clean-after">--</span> 条</p>
    <p>删除/去重：<span id="clean-removed">--</span> 条</p>
    <p>清洗状态：<span id="clean-status">未开始</span></p>
    <p id="clean-message"></p>
</section>
```

Rename the table heading to `最新原始采集数据`, use the exact note `仅展示该日期最近10条，尚未经过手动数据清洗`, and retain the formal-data link with `selected_date`.

- [ ] **Step 4: Add the synchronous clean request handler**

In `main.js`, keep the collection polling logic unchanged and add separate clean element bindings and handler:

```javascript
cleanForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    cleanStatusElement.textContent = "正在清洗";
    cleanMessageElement.textContent = "";
    try {
        const response = await fetch("/api/clean", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({date: cleanForm.elements.date.value}),
        });
        const result = await readResponse(response);
        cleanBeforeElement.textContent = result.before_count;
        cleanAfterElement.textContent = result.after_count;
        cleanRemovedElement.textContent = result.removed_count;
        cleanStatusElement.textContent = "清洗完成";
        cleanMessageElement.textContent = result.message;
    } catch (error) {
        cleanStatusElement.textContent = "清洗失败";
        cleanMessageElement.textContent = error.message;
    }
});
```

Expose `clean()` from the Node test harness so the new behavior test invokes the real handler. Do not add polling or a clean background thread.

- [ ] **Step 5: Update README demonstration and HDFS path documentation**

Document both paths and replace the old single-step demo with:

```text
开始采集 -> videos_raw.jsonl -> 页面显示最新10条原始数据
开始数据清洗 -> pandas clean_video_data() -> videos.jsonl
数据查询/挖掘/Spark/知识库 -> videos.jsonl
```

State that scheduled collection writes only raw data, `/api/clean` is administrator-only, and existing formal history remains usable. Preserve the real external-integration status and `WinError 10013` evidence; do not claim a new Bilibili/HDFS run unless performed.

- [ ] **Step 6: Run focused UI tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/test_collection_flow.py
node tests/test_main_polling.js
```

Expected: Python collection tests PASS and Node reports all tests PASS, including the new clean form behavior.

- [ ] **Step 7: Run full verification**

Run:

```powershell
python -m pytest -q
python -m compileall -q app.py collector services analysis knowledge scheduler
git diff --check
rg -n "comment_count|stat\.reply|read_csv|to_csv|type=\"file\"" app.py collector services analysis knowledge scheduler templates static
```

Run Node tests:

```powershell
node tests/test_main_polling.js
```

Expected: complete Python suite PASS except explicitly documented environment skip/warning, compile succeeds, diff check is clean, forbidden-flow scan finds no production use, and Node tests PASS.

If HDFS is available, verify without deleting historical files:

```powershell
wsl.exe -d Ubuntu -- bash -lc "systemctl --user is-active hdfs-namenode.service; systemctl --user is-active hdfs-datanode.service; hdfs dfs -ls /bigdata_course/bilibili/date=2026-08-09"
```

Then use the Flask administrator page with a new test date or an explicitly chosen existing date: confirm collection changes only `videos_raw.jsonl`; capture the formal `videos.jsonl` line count before cleaning; click “开始数据清洗”; confirm the formal file updates afterward. Do not call real Bilibili from a restricted Codex network and do not describe unavailable external checks as passed.

- [ ] **Step 8: Commit Task 4**

```powershell
git add templates/collect.html static/js/main.js tests/test_collection_flow.py tests/test_main_polling.js README.md
git commit -m "feat: add manual cleaning controls"
```

- [ ] **Step 9: Confirm final repository state**

Run:

```powershell
git status --short --branch
git log --oneline -6
```

Expected: current branch remains `main`, worktree is clean, and the four implementation commits follow design commit `5d85ea5`.
