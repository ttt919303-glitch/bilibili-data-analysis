# Course Dataset Accumulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow repeated administrator-selected keyword collections to add only new BV records to one date-scoped raw course dataset and expose truthful progress toward 10000 records.

**Architecture:** The Flask task runner acquires a per-date process lock, then reads date-scoped raw HDFS data and passes its BV exclusion set into a HDFS-independent collector. The lock covers the complete read, collect, save, and final-count cycle so same-date tasks have exact start snapshots while different dates remain independent. The collector follows WBI pagination until the requested number of successful new details or actual exhaustion; server-rendered and task-status views use raw HDFS, the existing MySQL `success_count` field, and in-process task snapshots without inferring historical start counts from a later total.

**Tech Stack:** Python 3.11, Flask 3, pytest, requests, HDFS WebHDFS client, vanilla JavaScript, Node test runner.

## Global Constraints

- `target_count` means the number of different BV records requested for this task, never the total course target.
- `COURSE_DATASET_TARGET` defaults to exactly `10000` and only affects display and progress calculations.
- Use only date-scoped `videos_raw.jsonl` for collection exclusion and progress; never merge dates or read `videos.jsonl` for these calculations.
- Do not add tables, schema columns, APIs, checkpoints, keyword pools, auto-cleaning, messaging infrastructure, or video fields.
- The administrator keyword must pass unchanged after boundary whitespace trimming from API to MySQL, thread, collector, and WBI request.
- Every production behavior change follows RED, GREEN, REFACTOR.

---

### Task 1: WBI pagination and historical exclusion

**Files:**
- Modify: `collector/bilibili_collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Produces: `SearchPage(bvids: list[str], total_pages: int)` and `collect(keyword: str, target_count: int, collect_date: str, exclude_bvids: Optional[Collection[str]] = None, task_id: Optional[int] = None) -> list[dict]`.
- Consumes: the existing `_request_json` and `get_video_detail` functions.

- [ ] **Step 1: Write failing collector tests**

Add tests whose literal fixtures prove: WBI `numPages` is returned; excluded BV values never reach `get_video_detail`; a fully duplicate first page does not stop page 2; 50 details stop midway through page 3; result exhaustion returns a real partial count; 700 historical matches among 1000 results cause exactly 300 detail calls; the exact custom keyword reaches every search page.

- [ ] **Step 2: Run collector tests and confirm RED**

Run: `venv\Scripts\python.exe -m pytest tests/test_collector.py -q`

Expected: failures show missing `SearchPage`/`exclude_bvids` behavior and premature termination on a duplicate-only page.

- [ ] **Step 3: Implement the minimal collector behavior**

Parse `data.numPages` with a minimum of the current page, maintain separate historical and task-seen sets, skip both before detail calls, increment only after a successful detail response, log per-page counters, and stop only on target, empty page, last page, or explicit failure.

- [ ] **Step 4: Run collector tests and confirm GREEN**

Run: `venv\Scripts\python.exe -m pytest tests/test_collector.py -q`

Expected: all collector tests pass.

### Task 2: Task runner counts and status contract

**Files:**
- Modify: `app.py`
- Test: `tests/test_collection_flow.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: Task 1 `collect(..., exclude_bvids=..., task_id=...)`.
- Produces: status payload fields `existing_count`, `added_count`, `total_count`, `course_target` and in-process task snapshots keyed by task ID.

- [ ] **Step 1: Write failing task and status tests**

Cover reading raw before collector invocation; passing only raw BV exclusions; preserving the exact custom keyword through create/thread/collector; storing the HDFS service's atomic new-BV count as `success_count`; rereading raw for total; same-date task serialization with exact per-task start counts; different-date concurrency; successful partial exhaustion; failed zero-new result; 8000+300=8300; scheduler reuse without formal writes or cleaning; and status values for running and terminal tasks. A terminal status without an in-process snapshot may report the current raw total but must leave the historical `existing_count` unknown instead of calculating `total_count - success_count`.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `venv\Scripts\python.exe -m pytest tests/test_collection_flow.py tests/test_scheduler.py -q`

Expected: failures identify missing exclusion reads, incorrect success-count semantics, and absent status fields.

- [ ] **Step 3: Implement minimal runner and status changes**

Read raw and compute unique BV count at task start, register a task snapshot, pass exclusions and task ID to collector, save only new rows, use the HDFS date-lock merge result as the atomic added count, reread raw for total, update MySQL with that actual added count, and expose derived status counts without schema changes. Remove snapshots at terminal completion after recording any data needed by the response path.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `venv\Scripts\python.exe -m pytest tests/test_collection_flow.py tests/test_scheduler.py -q`

Expected: all focused tests pass and collection remains raw-only.

### Task 3: Date-scoped server-rendered course progress

**Files:**
- Modify: `config.py`
- Modify: `.env.example`
- Modify: `app.py`
- Modify: `templates/collect.html`
- Modify: `static/js/main.js`
- Test: `tests/test_config.py`
- Test: `tests/test_collection_flow.py`
- Test: `tests/test_main_polling.js`

**Interfaces:**
- Consumes: `read_raw_from_hdfs(selected_date)` and `COURSE_DATASET_TARGET`.
- Produces: server-rendered progress values and a date-change navigation to `/collect?date=YYYY-MM-DD`.

- [ ] **Step 1: Write failing page and JavaScript tests**

Cover the 10000 default, unique raw count for only the selected date, HTTP 200 with unknown count on HDFS failure, true percentages above 100 with a capped progress width, enabled collection after target, task summary rendering, raw-only latest-data note, and date change navigation that performs no collect or clean request.

- [ ] **Step 2: Run page and Node tests and confirm RED**

Run: `venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_collection_flow.py -q`

Run: `node --test tests/test_main_polling.js`

Expected: failures identify missing template context/elements and date-change navigation.

- [ ] **Step 3: Implement minimal server-rendered and client behavior**

Add `COURSE_DATASET_TARGET`, read date-scoped raw in `/collect`, distinguish HDFS failure from empty data, render a normal card and task summary, cap only the CSS width, and navigate on collection-date change. Keep the collect button enabled and leave cleaning independent.

- [ ] **Step 4: Run page and Node tests and confirm GREEN**

Run both focused commands from Step 2 and require zero failures.

### Task 4: Full regression and contract audit

**Files:**
- Modify only files required to fix regressions introduced by Tasks 1-3.

**Interfaces:**
- Consumes: all preceding task behavior.
- Produces: evidence that the complete repository contract remains intact.

- [ ] **Step 1: Run all non-Spark Python tests**

Run: `venv\Scripts\python.exe -m pytest -q --ignore=tests/test_spark_analysis.py`

Expected: all tests pass.

- [ ] **Step 2: Run the complete Python suite**

Run: `venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass when the local Java/Spark gateway is functional; otherwise record the exact pre-existing environment error separately.

- [ ] **Step 3: Run all Node tests**

Run: `node --test tests/*.js`

Expected: all tests pass.

- [ ] **Step 4: Run static verification**

Run: `venv\Scripts\python.exe -m compileall -q app.py collector services scheduler analysis knowledge tests`

Run: `git -c safe.directory='F:/新大数据开发b站项目' diff --check`

Run the repository forbidden-feature scan for dataset tables, checkpoints, automatic keyword expansion, automatic cleaning, new video fields, and message infrastructure; inspect each hit in context rather than treating approved test/spec prose as production behavior.

- [ ] **Step 5: Review the diff against every frozen requirement**

Confirm detail requests happen only after both exclusion checks, duplicate-only pages continue, `success_count` is added count, total comes from raw HDFS, the custom keyword remains exact, progress is date-scoped and raw-only, HDFS failure renders unknown rather than zero, and manual cleaning remains independent.

- [ ] **Step 6: Do not run live collection without explicit environment readiness**

If B站、MySQL and HDFS are currently available, run only the approved three-keyword small regression on one test date with target 20 each. Otherwise report it as not run and do not claim live evidence or send 10000 requests.
