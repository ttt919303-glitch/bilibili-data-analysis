# Playwright Browser Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated Playwright persistent-browser diagnostic environment without changing B站 collection or Flask routes.

**Architecture:** `browser_crawler.py` owns only project-local browser paths and synchronous persistent-context startup. `debug_browser_crawler.py` calls that helper to open the B站 homepage and reports only URL, title, and a coarse login state. No existing API collector, data file, or Flask route is called.

**Tech Stack:** Python 3.12, Playwright Python sync API, pytest, pathlib.

## Global Constraints

- Use only `PROJECT_ROOT / "browser_data"`; never inspect, copy, or reference a user Chrome profile or cookies.
- Do not implement search, DOM video parsing, pagination, CSV writes, or Flask UI in this stage.
- Never print cookie values, authentication tokens, account names, passwords, or local storage.
- Launch one visible persistent browser context only when a helper or diagnostic script is called.
- Keep `crawler.py` unchanged and retain all existing dependencies.

---

### Task 1: Add isolated browser configuration and test coverage

**Files:**
- Create: `.gitignore`
- Create: `tests/test_browser_crawler.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: a test module that imports `get_browser_data_dir()` and `launch_persistent_browser()` from `browser_crawler`.
- Produces: `playwright` as a Python dependency and ignored local browser/debug artifacts.

- [ ] **Step 1: Write the failing tests**

```python
def test_browser_data_dir_is_under_project_root():
    assert get_browser_data_dir() == Path(browser_crawler.__file__).resolve().parent / "browser_data"

def test_launch_uses_visible_project_local_persistent_context(monkeypatch):
    context = Mock()
    playwright = Mock(chromium=Mock(launch_persistent_context=Mock(return_value=context)))
    monkeypatch.setattr(browser_crawler, "sync_playwright", lambda: fake_manager(playwright))
    assert launch_persistent_browser() is context
    playwright.chromium.launch_persistent_context.assert_called_once_with(
        user_data_dir=str(get_browser_data_dir()), headless=False
    )
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests\\test_browser_crawler.py -v`

Expected: FAIL because `browser_crawler` is not yet implemented.

- [ ] **Step 3: Add the minimal configuration**

Add `playwright` to `requirements.txt`; add `browser_data/`, `debug/`, `playwright/.auth/`, `__pycache__/`, `*.pyc`, and `.pytest_cache/` to `.gitignore`.

- [ ] **Step 4: Run the focused test after implementation**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests\\test_browser_crawler.py -v`

Expected: PASS for path, launch options, startup error, and ignored-artifact checks.

### Task 2: Implement the browser-only helper and diagnostic script

**Files:**
- Create: `browser_crawler.py`
- Create: `debug_browser_crawler.py`
- Test: `tests/test_browser_crawler.py`

**Interfaces:**
- Produces: `get_browser_data_dir() -> Path`.
- Produces: `launch_persistent_browser() -> BrowserContext`, which raises `BrowserCrawlerError` with a user-readable browser-startup message.
- Produces: `open_bilibili_home() -> tuple[BrowserContext, Page]`, opening `https://www.bilibili.com/` without search or data extraction.

- [ ] **Step 1: Implement only the tested helpers**

```python
def get_browser_data_dir() -> Path:
    return Path(__file__).resolve().parent / "browser_data"

def launch_persistent_browser():
    browser_data_dir = get_browser_data_dir()
    browser_data_dir.mkdir(parents=True, exist_ok=True)
    manager = sync_playwright().start()
    return manager.chromium.launch_persistent_context(
        user_data_dir=str(browser_data_dir), headless=False
    )
```

Keep the Playwright manager alive through the context lifecycle and close it in the diagnostic script. Convert only startup failures into `BrowserCrawlerError`; do not consume errors silently.

- [ ] **Step 2: Add the diagnostic entry point**

The script prints the project browser-data path, opens only the B站 home URL, prints current URL/title and `可能已登录` or `未确认`, waits for terminal Enter, then closes its page/context/manager in `finally`.

- [ ] **Step 3: Run focused tests**

Run: `..\\.venv\\Scripts\\python.exe -m pytest tests\\test_browser_crawler.py -v`

Expected: all browser-environment unit tests pass without launching a graphical browser.

### Task 3: Install and verify the local browser runtime

**Files:**
- Modify: `README.md`
- Test: manual command-line diagnostic only

**Interfaces:**
- Documents: `..\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt`, `..\\.venv\\Scripts\\python.exe -m playwright install chromium`, and `..\\.venv\\Scripts\\python.exe debug_browser_crawler.py`.

- [ ] **Step 1: Verify Python package availability**

Run: `..\\.venv\\Scripts\\python.exe -c "import playwright; print('playwright ok')"`

- [ ] **Step 2: Install Chromium only if allowed by the environment**

Run: `..\\.venv\\Scripts\\python.exe -m playwright install chromium`

If download or GUI launch is unavailable, preserve the successful package/test evidence and report the exact command for the Windows machine; do not claim browser success.

- [ ] **Step 3: Run the full regression suite**

Run: `..\\.venv\\Scripts\\python.exe -m pytest -q`

Expected: existing 78 tests and all new browser-environment tests pass.
