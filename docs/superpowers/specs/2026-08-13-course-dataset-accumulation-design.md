# 课程数据集累计能力设计

## 目标与范围

管理员可以为同一个 `collect_date` 多次输入任意关键词并发起采集。每次任务的 `target_count` 表示本次希望新增的不同 BV 数量；课程总目标由 `COURSE_DATASET_TARGET` 独立配置，默认值为 10000，仅用于页面与状态展示。

本次修改保留现有 Flask、MySQL、HDFS、后台线程与手动清洗架构。不得新增数据表、进度 API、checkpoint、关键词池、跨日期聚合或自动清洗，也不得修改视频记录的 11 字段合同。

## 采集边界与数据流

`run_collection_task` 在调用 collector 前读取所选日期的 `videos_raw.jsonl`，按非空 `bvid` 建立 `existing_bvids` 和 `existing_count`。正式 `videos.jsonl` 不参与采集去重。

业务入口调用：

```python
collect(
    keyword,
    target_count,
    collect_date,
    exclude_bvids=existing_bvids,
    task_id=task_id,
)
```

`exclude_bvids` 默认为 `None`，不传时保持原有行为。collector 不读取 HDFS，只负责按管理员原样输入的关键词搜索 B 站、过滤历史与任务内重复 BV、请求新 BV 详情并返回本次新记录。

WBI 搜索结果包含当前页 BV 与真实 `numPages`。每次任务从第 1 页开始，直至达到本次新增目标、到达最后一页、搜索页为空或接口失败。某页没有新 BV 不构成停止条件。历史 BV 与本次任务已见 BV 必须在详情请求之前跳过；详情成功后才计入本次新增数量。

搜索第一页失败或尚未获得任何记录时失败；获得部分真实记录后发生后续搜索失败时保存已有部分记录并在日志中保留异常。不得生成数据补足目标。

## 保存、数量与状态

新记录继续调用 `save_raw_to_hdfs(new_records, collect_date)`。HDFS 服务保留读取旧 raw、合并、按 BV keep-last 去重、交换写回的现有实现，并继续作为最终去重防线。

三个数量定义如下：

- `existing_count`：任务开始前，该日期 raw 中非空不同 BV 数量。
- `added_count`：本次成功取得详情并保存的新 BV 数量，等于 MySQL `success_count`。
- `total_count`：保存完成后重新读取该日期 raw 得到的非空不同 BV 数量。

业务线程不能把 HDFS 总量当作 `success_count`。`save_raw_to_hdfs` 在同日期写锁内比较合并前后的 BV 集合，返回本次原子写入真正新增的 BV 数，避免同日期并发任务重复计数；保存后重新读取 raw，确认真实 `total_count`。结果耗尽但新增大于 0 时仍为 `success`，消息为“目标新增 N 条，实际新增 M 条”；新增为 0 时为 `failed`，消息为“该关键词未发现新的唯一视频”。

同一进程内以 `task_id` 为键的任务进度快照保存该任务真正取得日期级执行权后的 `existing_count`、原子 `added_count` 和当时 `total_count`。任务刚创建、首次 HDFS 读取尚未完成而快照不存在时，`existing_count` 与 `total_count` 返回 `null`，页面显示 `--`，不得用 0 冒充真实数量。进程重启导致终态快照丢失时，状态 API 可以重新读取 raw 得到当前 `total_count`，但 `existing_count` 必须返回 `null`，不得用 `total_count - success_count` 推断并发任务的历史开始数量。API 返回 `existing_count`、`added_count`、`total_count` 和 `course_target`，不修改 MySQL 表结构。

同一个 `collect_date` 的完整采集周期使用单进程日期级 `threading.Lock` 串行执行，锁范围覆盖读取 existing raw、建立排除集、B 站采集、raw 保存和最终总量读取。等待锁的任务保持 `waiting`，取得执行权后才标记 `running`；不同日期使用不同锁并可独立执行。HDFS 服务原有的短期日期写锁继续保留。

## 页面与日期切换

`/collect?date=YYYY-MM-DD` 服务端读取所选日期的 `videos_raw.jsonl`，按不同非空 BV 计算当前进度。管理员修改日期输入框时，前端直接导航到 `/collect?date=<所选日期>`；这只重新加载页面，不触发采集或清洗，也不新增 AJAX 进度查询。

页面显示课程目标、当前 raw 唯一 BV 数量和完成度。若 HDFS 不可用，页面保持 HTTP 200，当前数量显示 `--`，并显示“无法读取数据量，请检查HDFS”，不得伪装成 0。达到或超过目标后显示真实数量与真实百分比，进度条视觉宽度封顶 100%，显示“已达到课程数据量目标”，但采集按钮保持可用。

任务区显示关键词、本次希望新增、采集前已有、本次实际新增、当前原始数据总量、课程目标和完成度。最新 raw 数据仍只显示最近 10 条，并明确完整数量以上方统计为准。

## 定时任务与清洗

定时任务继续使用 `DEFAULT_KEYWORD` 和 `DEFAULT_TARGET_COUNT`，通过同一个 `run_collection_task` 读取昨日 raw 并排除已有 BV。采集只写 `videos_raw.jsonl`；管理员点击 `/api/clean` 后才执行清洗并写 `videos.jsonl`。

## 错误与可观测性

每页记录 `task_id`、`keyword`、`page`、`search_count`、`existing_skipped`、`task_duplicate_skipped`、`detail_success`、`detail_failed`、`added_total` 和 `target_count`。零新增终态日志额外包含 `existing_count`、`pages_scanned` 和 `new_bvid_count=0`。日志不得包含代理地址或其他敏感配置。

HDFS 读取、保存和 B 站接口错误继续快速失败并记录完整服务端异常；面向用户的状态消息保持安全、明确，不吞掉真实错误。

## 验证

测试先覆盖历史 BV 在详情前跳过、全重复页继续翻页、多页新增目标、结果耗尽、零新增、自定义关键词全链路、8000 到 8300 的累计、状态数量、超过 10000 仍可采集、日期切换服务端进度、HDFS 不可用页面、手动清洗与定时任务不回归。

完成后运行完整 Python pytest、完整 Node 测试、`compileall`、`git diff --check` 与禁止项扫描。真实 B 站/HDFS 回归只允许同一日期下三个关键词各 20 条的小规模测试；不得自动发起 10000 条采集。
