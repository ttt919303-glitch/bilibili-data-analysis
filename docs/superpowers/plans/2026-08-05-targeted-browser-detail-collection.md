# Targeted Browser Detail Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make normal browser collection enrich only its newly saved videos, then recoverably replace the 943 incomplete URLs with 943 real fully detailed videos.

**Architecture:** Extend the existing interaction collector with an optional explicit target URL list and share the batch runner between global repair and targeted collection. Flask computes new URLs by comparing the raw CSV before and after the existing search collector. A separate one-time replacement script owns backup, precise deletion, state pruning, replacement collection, and final invariant checks.

**Tech Stack:** Python 3.11, Flask, pandas, Playwright synchronous API, pytest.

## Global Constraints

- Use `channel="msedge"` and project-local `browser_data/`; never read a default browser profile or export cookies.
- Browser request limit remains 1–200; API limit and `crawler.py` remain unchanged.
- Keep the non-blocking `threading.Lock` and `try/finally` release.
- Session stores only small summaries, never video lists, complete exceptions, cookies, or page HTML.
- Do not automatically run cleaning, HDFS, Spark, mining, model training, or QA.
- Do not fabricate rows or metric values; all replacement data must come from real Bilibili pages.

---

### Task 1: Add targeted detail collection

**Files:**
- Modify: `browser_interaction_backfill.py`
- Modify: `run_interaction_backfill.py`
- Test: `tests/test_browser_interaction_backfill.py`
- Test: `tests/test_run_interaction_backfill.py`

**Interfaces:**
- Produces: `get_supported_video_urls(path: Path | None = None) -> list[str]`.
- Produces: `backfill_bilibili_interactions(limit: int = 50, target_urls: Iterable[str] | None = None) -> dict[str, object]`.
- Produces: `run_target_batches(target_urls: Iterable[str], report: Callable) -> dict[str, object]`.

- [ ] Write a failing test proving a requested target URL is visited while an unrelated pending historical URL is not.
- [ ] Run the focused test and confirm it fails because `target_urls` is not accepted.
- [ ] Implement ordered target normalization, intersection with CSV URLs, and target-scoped progress.
- [ ] Run the focused test and existing interaction tests.
- [ ] Write a failing runner test proving target URLs are forwarded to every batch.
- [ ] Implement `run_target_batches` by sharing the existing batch loop without changing `run_all_batches` behavior.
- [ ] Run both interaction test modules.

### Task 2: Connect Flask to only newly saved URLs

**Files:**
- Modify: `app.py`
- Test: `tests/test_browser_crawl_flask.py`

**Interfaces:**
- Consumes: `get_supported_video_urls` and `run_target_batches` from Task 1.

- [ ] Write a failing Flask test with pre-existing historical URLs and one newly saved URL.
- [ ] Assert that detail collection receives only the newly saved URL.
- [ ] Run the focused test and confirm the current global runner makes it fail.
- [ ] Snapshot URLs before and after `crawl_bilibili_browser`, compute ordered new URLs, and call `run_target_batches`.
- [ ] Keep the current lock, session summary, flash states, and `/data` redirect behavior.
- [ ] Run the complete Flask browser test module.

### Task 3: Add recoverable incomplete-data replacement workflow

**Files:**
- Create: `replace_incomplete_videos.py`
- Test: `tests/test_replace_incomplete_videos.py`

**Interfaces:**
- Produces: `prepare_replacement() -> ReplacementPlan` that creates timestamped backups, deletes incomplete rows, and prunes state.
- Produces: `collect_replacements(plan: ReplacementPlan) -> int` that repeatedly collects search results and targets only each batch's new URLs.
- Produces: `verify_replacement(plan: ReplacementPlan) -> dict[str, int]` that fails unless all count and completion invariants hold.

- [ ] Write a failing test using duplicate incomplete rows and a completed row.
- [ ] Assert backups exist, every incomplete row is removed, the completed row remains, and deleted failures are pruned from state.
- [ ] Implement backup and atomic CSV/state replacement.
- [ ] Run the focused deletion test.
- [ ] Write a failing collection test proving failed new URLs are removed and replacements continue until the requested completed count is reached.
- [ ] Implement keyword rotation, per-batch targeted details, failed replacement removal, and final invariant verification.
- [ ] Run the replacement workflow tests.

### Task 4: Execute and verify

**Files:**
- Modify at runtime: `data/videos.csv`
- Modify at runtime: `data/interaction_backfill_state.json`
- Create at runtime: `data/backups/<timestamp>/videos.csv`
- Create at runtime: `data/backups/<timestamp>/interaction_backfill_state.json`

- [ ] Confirm no Python collector process is using the files or project profile.
- [ ] Run all mock tests and confirm they pass before touching production data.
- [ ] Run `python replace_incomplete_videos.py` and monitor until it reports 943 replacements completed.
- [ ] Audit unique URL counts, five detail fields, UP names, publish dates, crawl dates, and state coverage.
- [ ] Run `python -m pytest -q` and record the fresh passing count.
- [ ] Do not run cleaning, HDFS upload, Spark, mining, model training, or QA automatically.
