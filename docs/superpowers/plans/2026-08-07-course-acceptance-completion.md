# Course Acceptance Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐统一 HDFS 读取、全系统日期筛选、本地 LangChain 知识库、每日采集任务和采集后流水线，并保持现有功能兼容。

**Architecture:** 单体 Flask 内新增四个边界清晰的小模块：日期、知识库、每日流水线、调度器；所有分析统一通过 `load_analysis_dataframe` 读取 Pandas DataFrame，再按业务日期切片。外部系统通过参数和 mock 隔离，CSV/JSON 写入采用同目录临时文件原子替换。

**Tech Stack:** Python 3.11、Flask、Pandas、WebHDFS/CLI、PySpark、scikit-learn、LangChain Core、APScheduler、mlxtend、pytest。

## Global Constraints

- 保留默认端口 5052、固定登录账号、现有路由、页面风格与采集功能。
- 不引入 Celery、Redis、Docker、消息队列、微服务、付费 API 或运行时大型模型下载。
- 不覆盖仓库 `data/videos.csv` 与 `data/videos_cleaned.csv`；测试只写 `tmp_path`。
- HDFS/B站/浏览器在测试中必须 mock，HDFS 上传失败不得丢失本地数据。
- 默认业务日期为 `Asia/Shanghai` 昨天，可由 `APP_TIMEZONE` 覆盖。

---

### Task 1: Unified date and analysis source

**Files:**
- Create: `date_utils.py`
- Modify: `hdfs_utils.py`, `data_utils.py`, `mining.py`
- Test: `tests/test_acceptance_data_source.py`

**Interfaces:**
- Produces: `resolve_business_date(value, timezone_name) -> str`, `filter_by_publish_date(data, selected_date) -> DataFrame`, `load_analysis_dataframe(cleaned_path, raw_path, hdfs_cmd, hdfs_url, hdfs_user, allow_local_fallback=True) -> tuple[DataFrame, str]`.

- [ ] Write failing tests for yesterday, invalid dates, HDFS Web/CLI reads, fallback priority and mining delegation.
- [ ] Run the focused tests and confirm failures are caused by missing interfaces.
- [ ] Implement the minimal interfaces and atomic CSV helpers.
- [ ] Run the focused tests to green.

### Task 2: Date-aware Flask and Spark paths

**Files:**
- Modify: `app.py`, `spark_analysis.py`, `templates/base.html`, `templates/home.html`, `templates/data.html`, `templates/spark.html`, `templates/mining.html`, `templates/qa.html`
- Test: `tests/test_acceptance_dates.py`

**Interfaces:**
- Consumes: Task 1 date and data-source functions.
- Produces: all six requested endpoints accept `date`; forms and links preserve it; Spark accepts `selected_date` and filters before analyses.

- [ ] Write route tests for all pages, selected-date statistics, 400 invalid date, and empty-date message.
- [ ] Run them red.
- [ ] Add a request date helper, template date form, query propagation and Spark date filter.
- [ ] Run them green.

### Task 3: Local LangChain knowledge base

**Files:**
- Create: `knowledge_base.py`
- Modify: `qa.py`, `app.py`, `templates/qa.html`, `.gitignore`, `requirements.txt`
- Test: `tests/test_acceptance_knowledge_base.py`

**Interfaces:**
- Produces: `build_video_documents(data)`, `KnowledgeBaseService.prepare(data, selected_date, source)`, `KnowledgeBaseService.retrieve(question, top_k)`, and exact-answer dispatch through `qa.answer_question`.

- [ ] Write failing tests for Document fields, semantic retrieval, exact totals, date-separated indexes and metadata.
- [ ] Run them red.
- [ ] Implement LangChain Documents/splitter, TF-IDF Embeddings adapter, in-memory vector store/retriever and persisted fingerprint metadata.
- [ ] Connect QA route and run tests green.

### Task 4: Daily pipeline and scheduler

**Files:**
- Create: `daily_pipeline.py`, `scheduler.py`
- Modify: `app.py`, `templates/data.html`
- Test: `tests/test_acceptance_daily_pipeline.py`

**Interfaces:**
- Produces: `run_daily_pipeline(target_date=None, *, config=None, crawler=...) -> dict`, `start_scheduler(app) -> scheduler | None`.

- [ ] Write failing tests for exact publish-date filtering, URL normalization dedupe, cleaning, HDFS failure retention, status JSON, pytest suppression, repeat app creation and admin-only manual trigger.
- [ ] Run them red.
- [ ] Implement pipeline with dependency injection and atomic status writes; implement guarded BackgroundScheduler startup.
- [ ] Add status card and manual route, then run tests green.

### Task 5: Post-collection pipeline and locking

**Files:**
- Modify: `data_utils.py`, `app.py`, `browser_crawler.py`, `browser_interaction_backfill.py`
- Test: `tests/test_acceptance_post_collection.py`

**Interfaces:**
- Produces: one shared process lock and `run_post_collection_pipeline(app) -> dict`; `save_video_data` and JSON writes are atomic.

- [ ] Write failing tests that API/browser collection invokes cleaning/upload and keeps CSV when HDFS fails.
- [ ] Run them red.
- [ ] Reuse the common post-processing function from API, browser and manual daily routes.
- [ ] Run focused and existing browser/crawler tests green.

### Task 6: Fixed association rules

**Files:**
- Modify: `mining.py`, `app.py`, `templates/mining.html`
- Test: `tests/test_acceptance_mining_rules.py`

**Interfaces:**
- Produces: `run_required_association_rules(data) -> list[dict]`, always returning the three named rule slots with metrics or an explicit invalid status.

- [ ] Write failing tests for present and absent fixed rules.
- [ ] Run red, implement direct support/confidence/lift calculation, then run green.

### Task 7: Documentation and configuration

**Files:**
- Modify: `README.md`, `requirements.txt`, `.gitignore`
- Create: `.env.example`

- [ ] Document install/start/Hadoop/HDFS read-write/date selection/automatic task/manual trigger/knowledge-base build/test commands and real-environment caveats.
- [ ] Verify dependency names and ignored runtime artifacts.

### Task 8: Full verification

**Files:** all changed files.

- [ ] Run `python -m pytest tests -v` with the project virtualenv.
- [ ] Fix every failure through a regression test where applicable and rerun until exit code 0.
- [ ] Inspect `git diff --check`, `git status --short`, and confirm tracked production CSV hashes did not change.
