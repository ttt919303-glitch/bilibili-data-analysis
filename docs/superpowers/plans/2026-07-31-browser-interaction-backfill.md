# Browser Interaction Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill play, like, coin, favorite, and share counts for existing Bilibili videos through the project-local Edge session, 50 unique video URLs per run.

**Architecture:** Keep the accepted search crawler unchanged and create an isolated detail-page backfill module that reuses its persistent Edge launcher.  The module owns live-DOM interaction parsing, URL checkpointing, per-video CSV updates, and stop statuses; Flask only validates administrator access, acquires the existing browser lock, invokes the module, stores a small summary, and redirects to `/data`.

**Tech Stack:** Python, Playwright sync API, pandas, Flask, Jinja2, pytest, unittest.mock.

## Global Constraints

- Browser channel is `msedge`; use only the project-local `browser_data/` persistent session and visible browser windows.
- Use normal Bilibili video detail pages only; do not use APIs, cookies, passwords, CAPTCHA handling, stealth, proxies, concurrency, Redis, Celery, or automatic login.
- One run processes at most 50 distinct `video_url` values, sequentially, with a 3–6 second pause between detail pages.
- Preserve successful updates immediately; on timeout, verification, or page-structure failure stop without rolling back saved values.
- Do not automatically clean data, upload HDFS, run Spark, mining, or QA; do not modify `browser_crawler.py`, `crawler.py`, cleaning, HDFS, Spark, mining, or QA logic.
- The progress state stores only completed video URLs; it must not store browser/session data or page HTML and must be Git-ignored.

---

### Task 1: Verify the live detail-page DOM and capture a minimal fixture

**Files:**
- Create: `debug_browser_interactions.py`
- Create: `tests/fixtures/bilibili_video_interactions.html`

**Interfaces:**
- Consumes: `browser_crawler.launch_persistent_browser()` and one existing `video_url`.
- Produces: documented stable selectors for play, like, coin, favorite, and share counts, plus a minimal fixture derived from the observed page.

- [ ] **Step 1: Add a diagnostic command that opens one existing video URL**

```python
page.goto(video_url, wait_until="domcontentloaded", timeout=30_000)
print(page.url)
print(page.title())
```

The command must report only page state, selector counts, and visible count text; it must not print cookies or write video data.

- [ ] **Step 2: Run the diagnostic with project Edge and record actual selectors**

Run: `..\\.venv\\Scripts\\python.exe debug_browser_interactions.py --browser msedge`

Expected: a normal detail page with observable count elements, or an explicit verification/structure/timeout state.

- [ ] **Step 3: Create the smallest fixture from the observed HTML structure**

```html
<div class="observed-count-container">
  <span class="observed-play">10.5万</span>
  <span class="observed-like">532</span>
</div>
```

Use the real classes and nesting observed in Step 2; do not invent selectors or include unrelated page markup.

### Task 2: Add isolated backfill and checkpoint logic

**Files:**
- Create: `browser_interaction_backfill.py`
- Modify: `.gitignore`
- Test: `tests/test_browser_interaction_backfill.py`

**Interfaces:**
- Consumes: `launch_persistent_browser()`, `load_video_data(path)`, `save_video_data(data, path)`, and the Task 1 selectors.
- Produces: `backfill_bilibili_interactions(limit: int = 50) -> dict[str, object]` and `data/interaction_backfill_state.json`.

- [ ] **Step 1: Write failing parser and checkpoint tests**

```python
def test_parse_detail_metrics_converts_real_display_values():
    metrics = parse_detail_metrics(card_from_fixture())
    assert metrics == {"play_count": 105000, "like_count": 532, "coin_count": 12, "favorite_count": 34, "share_count": 5}
```

```python
def test_backfill_updates_all_rows_with_a_completed_url(tmp_path, monkeypatch):
    result = backfill_bilibili_interactions(limit=1)
    assert result["updated_count"] == 1
    assert completed_urls(state_path) == {"https://www.bilibili.com/video/BV1test"}
```

- [ ] **Step 2: Run the parser/checkpoint tests and verify they fail**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_interaction_backfill.py -q`

Expected: FAIL because the module and parser do not exist.

- [ ] **Step 3: Implement minimal isolated data flow**

```python
pending_urls = [url for url in unique_urls(data) if url not in completed_urls(state_path)][:limit]
for video_url in pending_urls:
    metrics = load_detail_metrics(page, video_url)
    data.loc[data["video_url"] == video_url, list(metrics)] = list(metrics.values())
    save_video_data(data, data_path)
    mark_completed(state_path, video_url)
```

Record a state URL only after its CSV update succeeds.  Return `success`, `partial`, `verification_required`, `page_structure_error`, or `page_timeout` with planned, updated, skipped, and processed counts.

- [ ] **Step 4: Add stop-status tests**

```python
def test_backfill_stops_on_verification_and_keeps_prior_update(monkeypatch):
    result = backfill_bilibili_interactions(limit=2)
    assert result["status"] == "verification_required"
    assert result["updated_count"] == 1
```

Cover timeout, structure error, state resume, 50-limit validation, and a genuine zero metric that is nevertheless checkpointed.

- [ ] **Step 5: Run module tests**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_interaction_backfill.py -q`

Expected: PASS.

### Task 3: Add administrator-only `/data` integration

**Files:**
- Modify: `app.py`
- Modify: `templates/data.html`
- Test: `tests/test_browser_interaction_backfill_flask.py`

**Interfaces:**
- Consumes: `backfill_bilibili_interactions(limit=50) -> dict[str, object]`.
- Produces: `POST /data/browser-backfill` and one-session `browser_backfill_result` summary.

- [ ] **Step 1: Write failing Flask tests**

```python
response = user_client.post("/data/browser-backfill")
assert response.status_code == 403
```

```python
with patch("app.backfill_bilibili_interactions", return_value=backfill_result("success")):
    response = admin_client.post("/data/browser-backfill", follow_redirects=True)
assert "互动数据回填完成" in response.get_data(as_text=True)
```

- [ ] **Step 2: Run the Flask tests and verify they fail**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_interaction_backfill_flask.py -q`

Expected: FAIL because the route and template control do not exist.

- [ ] **Step 3: Implement the thin route and result rendering**

```python
if not browser_crawl_lock.acquire(blocking=False):
    flash("浏览器采集任务正在运行，请等待当前任务完成。", "danger")
    return redirect(url_for("data_management"))
try:
    result = backfill_bilibili_interactions(limit=50)
finally:
    browser_crawl_lock.release()
```

Store only `planned_count`, `updated_count`, `skipped_count`, `processed_count`, `status`, and current raw total in session.  The template adds one administrator control labeled “回填互动数据（50条）”; it must not add a second keyword/limit form or alter API limits.

- [ ] **Step 4: Run Flask integration tests**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_interaction_backfill_flask.py -q`

Expected: PASS.

### Task 4: Documentation and verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_browser_interaction_backfill.py`, `tests/test_browser_interaction_backfill_flask.py`

- [ ] **Step 1: Document the manual 50-video backfill workflow**

Explain the Edge prerequisite, the 50-video batch cap, human verification stop, state-file resume behavior, and manual cleaning requirement after backfill.

- [ ] **Step 2: Run a real 50-video Edge backfill only after mock tests pass**

Run the administrator route against `/data/browser-backfill`; record the before/after SHA-256 of `data/videos.csv`, unchanged row count, the number of updated rows, and whether verification appeared.

- [ ] **Step 3: Run the complete suite**

Run: `..\\.venv\\Scripts\\python.exe -m pytest -q`

Expected: all tests pass.
