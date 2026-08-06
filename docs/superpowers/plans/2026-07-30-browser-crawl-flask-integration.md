# Browser Crawl Flask Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an administrator start the verified Edge browser crawler from `/data` and receive a saved-result summary after the synchronous crawl finishes.

**Architecture:** Keep browser crawling in `browser_crawler.py` and add one thin Flask adapter route.  The adapter validates request data, holds a process-local non-blocking lock, delegates to `crawl_bilibili_browser(keyword, limit)`, stores its returned summary in the session, then redirects to the existing data page.

**Tech Stack:** Flask, Jinja2, pytest, unittest.mock, Playwright through the existing browser crawler.

## Global Constraints

- Only administrators may access `POST /data/browser-crawl`; ordinary users receive the existing 403 page.
- Browser limits are integers from 1 through 200; API limits remain unchanged.
- Reuse the single existing keyword/limit input pair, preserve API crawl, CSV import, cleaning, HDFS, Spark, mining, and QA.
- Use the existing project-local Microsoft Edge persistent session; do not add headless mode, cookies, CAPTCHA handling, proxies, queues, or asynchronous services.
- Do not modify `browser_crawler.py`, `crawler.py`, `spark_analysis.py`, `mining.py`, `qa.py`, or `hdfs_utils.py`.

---

### Task 1: Flask browser-crawl route and results

**Files:**
- Modify: `app.py`
- Test: `tests/test_browser_crawl_flask.py`

**Interfaces:**
- Consumes: `browser_crawler.crawl_bilibili_browser(keyword: str, limit: int) -> dict[str, object]`
- Produces: `POST /data/browser-crawl`, plus `session["browser_crawl_result"]` for the `/data` template.

- [ ] **Step 1: Write failing route tests**

```python
response = client.post("/data/browser-crawl", data={"keyword": "Python", "limit": "20"})
assert response.status_code == 403
```

```python
with patch("app.crawl_bilibili_browser", return_value=browser_result("success")):
    response = admin_client.post("/data/browser-crawl", data={"keyword": "Python", "limit": "20"}, follow_redirects=True)
assert "浏览器采集完成" in response.get_data(as_text=True)
```

- [ ] **Step 2: Run the new route tests and verify the route is absent**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_crawl_flask.py -q`

Expected: FAIL because `/data/browser-crawl` is not registered.

- [ ] **Step 3: Add the minimal route**

```python
if not browser_crawl_lock.acquire(blocking=False):
    flash("浏览器采集任务正在运行，请等待当前任务完成。", "danger")
    return redirect(url_for("data_management"))
try:
    result = crawl_bilibili_browser(keyword, limit)
finally:
    browser_crawl_lock.release()
```

Validate empty keywords and browser-only limits before calling the crawler; map each documented crawler status to a user-facing flash message and preserve saved partial counts.

- [ ] **Step 4: Run the route tests**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_crawl_flask.py -q`

Expected: PASS.

### Task 2: Data-page controls, summary, and guidance

**Files:**
- Modify: `templates/data.html`
- Modify: `README.md`
- Test: `tests/test_browser_crawl_flask.py`

**Interfaces:**
- Consumes: `browser_crawl_result` supplied by `data_management()`.
- Produces: one shared keyword/limit form with browser and API submit buttons, and an accessible browser result summary.

- [ ] **Step 1: Write failing page-content tests**

```python
response = admin_client.get("/data")
body = response.get_data(as_text=True)
assert "浏览器采集（推荐）" in body
assert "API采集（备用）" in body
```

- [ ] **Step 2: Run the page-content test and verify it fails**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_crawl_flask.py -q`

Expected: FAIL because the browser control and summary do not exist.

- [ ] **Step 3: Add minimal template and README changes**

Use `formaction="{{ url_for('browser_crawl_data') }}"` for the recommended button and retain `action="{{ url_for('crawl_data') }}"` for API collection.  Render planned, saved, parsed, skipped, pages, total, and mapped status from the crawler result; document manual login through `debug_browser_crawler.py --browser msedge` and that `browser_data/` is not committed.

- [ ] **Step 4: Run focused tests and the complete suite**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests/test_browser_crawl_flask.py -q`

Expected: PASS.

Run: `..\\.venv\\Scripts\\python.exe -m pytest -q`

Expected: all tests pass.
