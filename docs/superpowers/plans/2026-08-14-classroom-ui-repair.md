# Classroom UI Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the classroom presentation layout, keep all existing data and analysis behavior, and verify real Spark charts from an ASCII Windows path.

**Architecture:** Build the authenticated application shell in the shared base template, then use page-specific semantic classes for wide tables, compact controls, metric blocks, and charts. Keep mining and Spark computation untouched; expose only existing record counts to templates and perform Spark recovery through runtime environment/path setup.

**Tech Stack:** Flask 3, Jinja2, HTML, CSS, pytest, vanilla JavaScript, ECharts 5, PySpark 3.5.1, HDFS WebHDFS.

## Global Constraints

- Keep the ordinary undergraduate course-project visual style.
- Do not modify Bilibili collection logic, HDFS structure, mining algorithms, Spark analysis algorithms, database structure, or the 11-field contract.
- Do not add React, Vue, Tailwind, a dashboard framework, an icon library, an animation library, or another frontend dependency.
- The prediction model must process every formal record; only the rendered example list is limited to 20 rows.
- Do not hide Spark errors or substitute pandas/static data for Spark output.
- Use `collect_date=2026-08-14` for real browser acceptance.

---

### Task 1: Add UI Contract Tests

**Files:**
- Modify: `tests/test_pages.py`
- Modify: `tests/test_mining.py`

**Interfaces:**
- Consumes: existing Flask `client` fixture and page routes.
- Produces: regression contracts for authenticated shell, login isolation, responsive data table, dynamic formal-data count, and 20-row prediction rendering.

- [ ] **Step 1: Write failing shell and data page tests**

Add tests that log in, render `/data?date=2026-08-14`, and assert the response contains `class="sidebar"`, the unified project title, `class="table-responsive`, a title tooltip, and `当前正式数据：2 条`. Add a logged-out `/login` assertion that the sidebar is absent.

- [ ] **Step 2: Write the failing prediction example test**

Build 25 complete record fixtures, replace only the three expensive algorithm boundaries with deterministic complete result structures, render `/mining`, and assert the page says the model used all 25 records while showing `BV19` and omitting `BV20`.

- [ ] **Step 3: Run tests to verify RED**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_pages.py tests/test_mining.py -q`

Expected: failures for missing sidebar/table classes, missing dynamic count, and unbounded prediction output.

---

### Task 2: Implement the Shared Classroom Layout and Wide Result Pages

**Files:**
- Modify: `app.py`
- Modify: `templates/base.html`
- Modify: `templates/data.html`
- Modify: `templates/mining.html`
- Modify: `templates/visualization.html`
- Modify: `static/css/style.css`

**Interfaces:**
- Consumes: `request.endpoint`, the existing session, existing route result dictionaries, and existing ECharts `analysis` payload.
- Produces: `dataset_count: Optional[int]` and `video_count: int` template values; semantic layout/table classes consumed only by CSS.

- [ ] **Step 1: Add the minimal route context**

In `data_page()`, compute `dataset_count = None` on HDFS error and `len(videos)` after a successful read, then pass it to `data.html`. In `mining_page()`, pass `video_count=len(videos)` without changing any algorithm call.

- [ ] **Step 2: Build the authenticated shell**

Render `.app-shell`, `.sidebar`, route-aware `.menu-link.active`, `.page-wrapper`, `.top-header`, and `.main-content` only when `session.user_id` exists. Render only `.login-main` for logged-out pages.

- [ ] **Step 3: Repair the data page**

Use `.compact-form`, a dynamic formal-data count, `.table-responsive`, fixed table column groups, non-wrapping BV/numeric cells, three-line title cells, and `title="{{ video.title }}"`. Preserve query, pagination, HDFS error, and link behavior.

- [ ] **Step 4: Repair the mining page**

Use a compact date form, responsive KMeans/Apriori tables, four metric blocks, and a prediction table iterating over `results.hot_prediction.predictions[:20]`. Render the sentence `模型基于全部 {{ video_count }} 条正式数据计算，以下仅展示前20条预测结果。`.

- [ ] **Step 5: Repair the Spark presentation**

Keep the four chart containers and analysis payload unchanged, render the chart grid only when real analysis exists, retain truncated axis labels and full tooltip names, and change only the bar emphasis color to green.

- [ ] **Step 6: Implement restrained responsive CSS**

Set a 210px dark sidebar, wide 1280px content region, centered top header, white cards, green buttons/active menu, responsive compact forms, scrollable wide tables, fixed column widths, safe title wrapping, non-wrapping metrics, and 2×2 desktop charts. Collapse to a top menu/single-column charts below 800px.

- [ ] **Step 7: Run focused tests to verify GREEN**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_pages.py tests/test_mining.py tests/test_auth.py -q`

Expected: all focused tests pass.

---

### Task 3: Recover and Verify the Real Spark Runtime Without Production Changes

**Files:**
- No repository file modifications.
- Temporary runtime path: `F:\bigdata_bilibili` directory junction to the repository, removed after acceptance.

**Interfaces:**
- Consumes: `JAVA_HOME`, the project venv, PySpark 3.5.1 jars, `.env`, WebHDFS, and the fixed date formal JSONL.
- Produces: environment evidence and a running Flask server whose `/visualization?date=2026-08-14` uses real Spark results.

- [ ] **Step 1: Capture runtime evidence**

Record `JAVA_HOME`, `SPARK_HOME`, PATH Java resolution, `java -version`, `spark-submit --version`, Python executable, PySpark version, project path, and WebHDFS status.

- [ ] **Step 2: Create and validate the ASCII junction**

Create `F:\bigdata_bilibili` as a junction to the current repository after confirming the target. Set `SPARK_HOME=F:\bigdata_bilibili\venv\Lib\site-packages\pyspark`, `PYSPARK_PYTHON=F:\bigdata_bilibili\venv\Scripts\python.exe`, `SPARK_SCALA_VERSION=2.12`, and prepend `%JAVA_HOME%\bin` to PATH.

- [ ] **Step 3: Run the Spark integration test outside the restricted sandbox**

Run: `F:\bigdata_bilibili\venv\Scripts\python.exe -m pytest tests/test_spark_analysis.py -q -ra`

Expected: the Java gateway binds locally and the real Spark integration test passes. If it still fails, preserve the full stack trace and stop Spark claims.

- [ ] **Step 4: Start Flask from the ASCII path**

Start the existing app with the same environment and no source modifications. Confirm port 5000 and WebHDFS before browser navigation.

---

### Task 4: Real Browser Acceptance and Full Regression

**Files:**
- Create screenshots under `tmp/classroom-ui/` only.

**Interfaces:**
- Consumes: the authenticated local Flask app and formal HDFS dataset for `2026-08-14`.
- Produces: `data.png`, `mining.png`, and `visualization.png` visual evidence plus final regression output.

- [ ] **Step 1: Verify `/data` in the browser**

Confirm the nine-column table is readable, title cells remain inside the card, numeric cells do not render vertically, width is appropriate, pagination links work, and a title/UP search returns filtered rows. Save `tmp/classroom-ui/data.png`.

- [ ] **Step 2: Verify `/mining` in the browser**

Confirm KMeans has four orderly columns, four prediction metrics are readable, exactly 20 prediction examples are rendered, long titles stay inside the table, prediction labels do not render vertically, and Apriori remains visible. Save `tmp/classroom-ui/mining.png`.

- [ ] **Step 3: Verify `/visualization` in the browser**

Confirm the page contains four populated ECharts instances backed by the real Spark response, arranged 2×2 at desktop width, with no Spark error message. Save `tmp/classroom-ui/visualization.png`.

- [ ] **Step 4: Stop Flask and remove the validated temporary junction**

Stop only the Flask process started for this acceptance run, verify port 5000 is closed, validate the junction target, and remove the junction without touching the source repository.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest -q -ra
node --test tests/test_main_polling.js
.\venv\Scripts\python.exe -m compileall -q -f app.py analysis collector knowledge scheduler services tests
.\venv\Scripts\python.exe -m pytest tests/test_project_contract.py -q
git diff --check
git diff --stat
git diff --name-only
git status --short
```

Expected: Python and Node tests pass, compilation and contract scans pass, and the diff contains no collector, HDFS, mining algorithm, Spark algorithm, schema, or dataset changes.
