# Targeted Browser Detail Collection Design

## Goal

Make one click on “浏览器采集（推荐）” collect search metadata and the five detail metrics for only the videos added by that click, then replace the 943 currently incomplete URLs with real newly collected, fully detailed videos.

## Scope

- Keep Microsoft Edge, the project-local `browser_data/`, visible persistent context, search DOM parsing, API crawler, cleaning, HDFS, Spark, mining, and QA behavior unchanged.
- Add a target URL boundary to the existing detail collector so callers can explicitly request a finite set of newly added URLs.
- Keep the existing global historical backfill entry for old data, but do not call it from normal browser collection.
- Back up `videos.csv` and `interaction_backfill_state.json` before deleting the 943 incomplete URLs.
- Delete every raw CSV row belonging to those 943 normalized URLs, including 19 duplicate rows, then prune their state entries.
- Collect real replacements until 943 new unique URLs have completed all five detail metrics. Failed replacement URLs are removed and replaced; no fabricated rows or random metrics are allowed.

## Data Flow

1. Snapshot normalized URLs in `videos.csv` before search collection.
2. Run the existing `crawl_bilibili_browser(keyword, limit)` search collector.
3. Snapshot normalized URLs again and calculate the ordered set difference.
4. Run detail collection only for that set difference.
5. Persist each successful video's play, like, coin, favorite, and share counts immediately.
6. Return a small summary to Flask and redirect to `/data`; do not trigger cleaning or downstream analysis.

## Failure Rules

- Verification stops the current target batch and requires manual action.
- Timeout or page structure failures remain observable in the state file and result summary.
- A replacement URL that cannot complete after the bounded attempts is removed from the raw CSV and state before another real replacement is collected.
- Existing completed rows are never deleted or reprocessed by the replacement workflow.

## Success Criteria

- The normal browser route never processes unrelated historical URLs.
- Exactly 943 incomplete normalized URLs are removed recoverably.
- Exactly 943 real new normalized URLs are added and marked completed.
- The final raw dataset has 10,097 unique supported normal video URLs, with every URL marked completed and all five metrics collected from a detail page.
- Targeted browser tests and the complete pytest suite pass.
