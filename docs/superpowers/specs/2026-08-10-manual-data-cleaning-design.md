# 数据采集与手动清洗分离设计

## 目标

把现有“采集后自动清洗并写入正式数据”的流程改为两个独立演示步骤：采集任务只保存原始数据，管理员手动触发 pandas 清洗后才更新正式数据。项目继续保持单 Flask 进程、本科课程作业复杂度，不新增任务系统、线程、数据库表或工程化组件。

## 固定数据路径

- 原始采集数据：`/bigdata_course/bilibili/date=YYYY-MM-DD/videos_raw.jsonl`
- 清洗后的正式数据：`/bigdata_course/bilibili/date=YYYY-MM-DD/videos.jsonl`

现有首页、`/data`、`/mining`、Spark 分析、`/visualization`、`/knowledge` 继续通过 `read_from_hdfs(date)` 读取正式 `videos.jsonl`，不得改为读取 raw。已有正式数据不删除、不迁移，也不因新增 raw 路径而覆盖为空。

## 采集流程

`run_collection_task()` 保持现有后台线程和 MySQL `collection_tasks` 状态更新方式，但执行顺序改为：

1. 将任务状态更新为 `running`。
2. 调用 `collector.collect(keyword, target_count, collect_date)` 采集 11 个固定字段。
3. 不调用 `clean_video_data()`。
4. 将采集结果交给 `save_raw_to_hdfs(data, date)`。
5. 至少成功写入 1 条时任务记为 `success`；少于目标数量时沿用“目标 N 条，实际采集 M 条”消息；0 条或整体失败时记为 `failed`。

同一天多次采集时，`videos_raw.jsonl` 按 `bvid` 合并，重复记录采用 `keep=last` 语义，形成当日累计原始数据。自动定时采集继续调用同一个 `run_collection_task()`，因此也只写 raw，不自动清洗。

## HDFS 服务

在 `services/hdfs_service.py` 增加：

- `raw_video_path(date)`：返回 `videos_raw.jsonl` 路径。
- `save_raw_to_hdfs(data, date)`：复用正式数据写入的日期锁、临时文件交换和按 `bvid` 合并逻辑，但写入 raw 路径。
- `read_raw_from_hdfs(date)`：读取 raw 路径；文件不存在时返回空列表。

现有 `save_to_hdfs()`、`read_from_hdfs()` 和 `video_path()` 的正式路径语义保持不变。为避免复制整段交换写入代码，可以在文件内部提取一个只供 raw/cleaned 两类公开函数复用的简单私有读写辅助函数，不增加新的服务层或抽象目录。

## 手动清洗 API

新增同步接口 `POST /api/clean`，请求 JSON 只包含 `date`。接口同时使用现有 `login_required` 和 `admin_required`：管理员可执行，普通用户返回 403。

处理顺序固定为：

1. 使用现有日期校验得到规范的 `YYYY-MM-DD`。
2. `read_raw_from_hdfs(date)` 读取当日全部 raw 数据。
3. raw 为空时返回清楚错误，不调用正式写入，避免覆盖已有 `videos.jsonl`。
4. 调用现有 `clean_video_data(raw_records)`。
5. 清洗结果为空时返回清楚错误，不覆盖已有正式数据。
6. `save_to_hdfs(cleaned_records, date)` 写入正式 `videos.jsonl`。
7. 返回 `before_count`、`after_count`、`removed_count` 和 `message`；其中 `removed_count = before_count - after_count`。

清洗接口不创建新数据库表，不使用后台线程；课程数据量下同步执行即可。异常按现有 Flask 错误风格返回明确消息并记录日志，不吞掉 HDFS 或 pandas 错误。

## 采集页面交互

`/collect` 保留采集区域，并增加一个简单的“数据清洗”区域：

- 清洗日期默认与页面选定日期一致。
- 管理员点击“开始数据清洗”后，JavaScript `POST /api/clean`。
- 页面展示清洗日期、清洗前数量、清洗后数量、删除/去重数量和清洗状态。

采集状态 API 继续返回 `latest_videos` 字段，但成功任务的数据来源固定改为 `read_raw_from_hdfs(date)`，最多返回最近 10 条。采集页表格标题改为“最新原始采集数据”，说明文字为“仅展示该日期最近10条，尚未经过手动数据清洗”。即使已经完成清洗，该表格仍只表示 raw 数据；清洗后的正式数据通过携带当前日期的 `/data?date=YYYY-MM-DD` 链接查看。

## 数据合同与范围

raw 与 cleaned 都只使用既定 11 字段：`bvid`、`title`、`video_url`、`up_name`、`publish_time`、`view_count`、`like_count`、`coin_count`、`favorite_count`、`share_count`、`collect_date`。不请求评论接口，不增加评论、`comment_count` 或 `stat.reply`，不引入 CSV 上传/下载中转。

本次不修改 KMeans、爆款预测、Apriori、Spark 四项分析、知识库设计、登录架构、定时任务架构和正式 HDFS 路径。

## 测试与验收

先写失败测试，再做最小实现，至少覆盖：

1. 采集任务不调用 `clean_video_data()`。
2. 采集任务调用 `save_raw_to_hdfs()`，不调用 `save_to_hdfs()`。
3. 采集完成不会修改正式 `videos.jsonl`。
4. raw 数据同日多次写入按 `bvid` 合并并采用最后一条。
5. 管理员可调用 `POST /api/clean`，普通用户得到 403。
6. 清洗 API 读取 raw、真实调用现有 `clean_video_data()` 并写入正式数据。
7. 清洗 API 返回 `before_count`、`after_count`、`removed_count`、`message`。
8. raw 为空或清洗结果为空时不覆盖已有正式数据。
9. 成功状态接口最多返回 10 条最新 raw 数据。
10. 页面含独立采集与清洗按钮、raw 说明和带日期的正式数据查询链接。
11. 首页、数据查询、挖掘、Spark、可视化和知识库仍读取正式数据入口。
12. 项目合同继续禁止 CSV 人工中转和评论相关字段。

完成后运行完整 Python 测试、Node 行为测试、`git diff --check`，并在具备 HDFS 环境时真实验证 raw 写入与手动清洗后正式文件更新；未实际联调的外部环节必须明确标注。
