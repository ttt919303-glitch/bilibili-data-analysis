# 模拟学生课堂演示端到端验收报告

## 验收信息

- 验收时间：2026-08-13（Asia/Shanghai）
- 分支与提交：`main` / `993ed95`
- 启动命令：`python app.py`（使用项目 Python 3.11.9 环境）
- 首次验收原则：只测试与报告；后续经用户确认，仅修复本报告中的 1 个 Important 和 1 个 Minor，未删除或格式化 HDFS/MySQL 数据，未生成假 B 站数据
- 测试数据日期：`2026-08-13`
- 关键字与目标数量：`大数据技术` / `3`

## 已真实验证

### 启动前与运行环境

- `git status --short --branch` 显示 `## main`，没有文件变更；`git branch --show-current` 为 `main`；`git rev-parse --short HEAD` 为 `993ed95`。
- `python --version` 为 Python 3.11.9，Flask 正常监听 `http://127.0.0.1:5000`，启动阶段没有异常。
- MySQL 8.0.41 在 `127.0.0.1:3306` 可连接，`bigdata_course` 数据库以及 `admin`、`student` 账号存在。
- Windows 侧访问 `http://127.0.0.1:9870` 和 WebHDFS 均被拒绝，错误为 `WinError 10061`；当前会话没有 `systemctl`、`jps`、`hdfs`、`java` 命令。
- 尝试执行 WSL 只读服务检查时被当前执行策略拒绝，未执行 HDFS 命令，也未执行任何格式化、删除或写入操作。因此 NameNode、DataNode、`Live datanodes (1)` 和历史 HDFS 文件未在本轮得到现场确认。
- `spark-submit --version` 失败，输出包括缺少 `python3`、找不到 Spark jars；`java -version` 不可用。

### 普通用户真实浏览器操作

- 使用本地环境配置的普通用户账号成功登录，登录后服务器重定向到首页。
- 普通用户导航不包含“数据采集”。
- 首次验收时，普通用户真实访问 `/`、`/data`、`/mining` 均稳定返回 500；对应 Flask 堆栈显示读取 `2026-08-12` 的 `videos.jsonl` 时无法连接 WebHDFS `127.0.0.1:9870`。修复后复测三页均返回 200，并显示“连接 HDFS 失败，请检查 Hadoop/HDFS 是否启动。”；首页统计显示 `--`，数据页不再把连接失败显示成“该日期暂无数据”，挖掘页不展示算法结果。
- `/knowledge` 返回正常 HTML 页面并显示“知识库构建失败”，没有返回 500。
- `/visualization` 返回正常 HTML 页面并显示“Spark 分析失败，请检查 Spark、Java 和 HDFS 环境”，没有返回 500，也没有伪造图表数据；日志保留了真实异常。
- 使用普通用户会话直接 POST `/api/collect` 与 `/api/clean`，两个接口均返回 403。
- 已执行退出登录。

### 管理员真实浏览器操作

- 使用本地环境配置的管理员账号成功登录，登录后服务器重定向到首页；首次验收首页因 HDFS 不可达返回 500，修复后首页正常返回 200 并显示 HDFS 环境提示。
- `/collect` 正常打开；页面明确分为“B 站视频数据采集”和“数据清洗”，结果区标题为“最新原始采集数据”，并提示“仅展示该日期最近10条，尚未经过手动数据清洗”。
- 页面和导航中的默认日期均为服务器昨天 `2026-08-12`。
- 输入 `大数据技术`、日期 `2026-08-13`、目标数量 `3` 后单击“开始采集”，页面真实经历 `running → failed`；没有生成成功状态或假数据。
- 首次验收最终页面显示实际成功采集 `0` 条，并直接显示 B 站底层异常。修复后任务 10 仍为 `failed`、实际成功采集 `0` 条，但页面只显示“B站数据采集失败，请检查网络连接或接口状态。”。
- MySQL 新增任务 9：`target_count=3`、`success_count=0`、`status=failed`、`collect_date=2026-08-13`、创建时间 `2026-08-13 04:41:52`、完成时间 `04:41:55`，`message` 与页面及服务日志一致。
- 同日单击“开始数据清洗”，页面经历“正在清洗 → 清洗失败”，提示检查 HDFS 与数据格式；服务日志表明根因是 WebHDFS `WinError 10061`。
- MySQL 最近 10 条任务记录已实际查询；任务 9 没有把失败伪装成成功，数量、状态、时间与消息一致。
- 修复后 MySQL 任务 10 为 `target_count=3`、`success_count=0`、`status=failed`，`message` 为简洁中文；同一次失败的完整 URL、`HTTPSConnectionPool`、对象地址和 `WinError 10013` 堆栈仍保留在 Flask 日志。

### 调度器现场检查

- 实际构建调度器后仅注册一个任务：`collect_yesterday`，触发器为每天 `00:10`，`max_instances=1`。
- 生产调用链为 `run_scheduled_collection()` → `run_collection_task()` → `save_raw_to_hdfs()`；没有调用 `clean_video_data()` 或 `save_to_hdfs()`。

## 自动测试验证

以下项目由最终自动测试或静态契约证明；现场联调结果见本文结论和 `final-verification-report.md`：

- 最终完整 Python 测试：`96 passed, 0 skipped, 1 warning`。原跳过项是 `tests/test_spark_analysis.py::test_four_spark_analyses_have_expected_order`；旧条件只查 `PATH` 中的 `java`，遗漏了有效 `JAVA_HOME`，已仅修正测试环境探测并真实运行通过。
- 完整 Node 测试：`7 passed, 0 failed`，覆盖清洗提交、返回数量、失败提示、过期响应隔离、轮询并发和瞬时错误恢复。
- `python -m compileall -q -f ...` 通过。
- `git diff --check` 通过。
- 禁用项契约 `tests/test_project_contract.py`：`4 passed`；生产目录扫描未发现评论采集、`comment_count`、`stat.reply`、CSV 上传/读写、Docker、Kafka、Celery、RabbitMQ 或 Redis 分布式锁。
- 采集与清洗分离：测试证明采集只写 `videos_raw.jsonl`，不调用清洗器且不写 `videos.jsonl`；调度器测试也禁止自动清洗。
- 正式清洗字段契约：测试证明结果固定为 11 个字段，并排除评论相关字段。
- 数据挖掘特征契约：KMeans、爆款预测的输入特征固定为 `like_count`、`coin_count`、`favorite_count`、`share_count`，`view_count` 只用于生成爆款标签，不是输入特征；KMeans 三类名称为“低互动 / 中互动 / 高互动”。
- 采集器已有自动分页、去重和异常数据测试；这些不能替代本轮未完成的真实 21 条 B 站分页采集。
- 默认日期契约由应用实现与测试证明为服务器昨天；现场可打开的采集、知识库和 Spark 页面也都显示 `2026-08-12`。

## 未验证（首次验收历史记录，已由最终复核覆盖）

- HDFS 的 `systemctl --user status`、`jps`、`hdfs dfsadmin -report`、`Live datanodes (1)` 以及历史目录：WSL 访问未获执行许可，Windows WebHDFS 端口当前拒绝连接。
- 新日期 `2026-08-13` 的 `videos_raw.jsonl` 和 `videos.jsonl`：真实采集在访问 B 站时失败，且 HDFS 不可达；未生成或检查文件。
- 手动清洗的真实 `videos_raw.jsonl → pandas → videos.jsonl` 数据闭环、实际清洗数量及正式文件 11 字段：没有 raw 输入且 HDFS 不可达。
- `/?date=2026-08-13`、`/data?date=2026-08-13` 的正式数据、搜索、UP 主搜索、分页、视频链接和日期切换：正式数据未生成且 HDFS 不可达。
- 历史日期上的 KMeans、爆款预测、Apriori 页面结果，以及四个知识库问题的同日数据复核：历史 HDFS 数据不可读。
- Spark：**未真实联调**。仅真实验证了缺失 Java/Spark/HDFS 时页面不会 500，并会显示明确错误。
- 真实 `target_count=21` 分页采集：B 站网络出现 `WinError 10013`，因此“真实21条分页采集本轮未验证”；未修改 collector，也未用重复 BV 或假数据补齐。

## 发现的问题

### 1. HDFS 不可用时三个核心学生页面直接返回 500

- 严重程度：Important
- 复现步骤：启动 Flask；使用本地环境配置的普通用户账号登录；依次访问 `/`、`/data`、`/mining`。
- 预期结果：页面正常显示数据，或在 HDFS 环境不可用时显示可理解的环境错误，不能返回 500。
- 实际结果：三个页面均显示浏览器默认的 `500 Internal Server Error`；学生无法继续课堂演示。
- 证据：浏览器三条路径标题均为 `500 Internal Server Error`。Flask 堆栈定位到 `app.py` 的 `index()`、`data_page()`、`mining_page()` 调用 `read_from_hdfs()`，随后 `services/hdfs_service.py` 因连接 `127.0.0.1:9870` 失败抛出 `HdfsServiceError`，错误码为 `WinError 10061`。
- 根因：这三个路由没有像 `/knowledge` 和 `/visualization` 那样捕获并渲染 HDFS/环境错误，服务层异常直接上抛给 Flask。
- 是否需要修复：需要，但按本轮规则等待确认后再做最小修复；本报告未修改生产代码。
- 修复状态：已按 TDD 修复并现场复测；新增测试先得到 `7 failed, 34 passed`，最小实现后目标测试 `41 passed`。

### 2. 采集失败把完整底层网络异常直接显示在管理员页面

- 严重程度：Minor
- 复现步骤：管理员进入 `/collect`；输入 `大数据技术`、`2026-08-13`、`3`；单击“开始采集”并等待失败。
- 预期结果：页面显示简洁、可理解的失败摘要，完整 URL、连接池和套接字细节保留在服务日志及任务诊断中。
- 实际结果：页面直接显示包含 B 站 URL、`HTTPSConnectionPool`、对象地址和 `WinError 10013` 的长异常文本，明显挤占演示页面。
- 证据：真实浏览器页面在任务状态 `failed` 下显示完整英文异常；MySQL 任务 9 的 `message` 保存了同一文本。
- 根因：`run_collection_task()` 将 `str(exc)[:500]` 直接写入 `collection_tasks.message`，状态接口原样返回该字段，前端直接渲染为用户提示。
- 是否需要修复：建议修复，但应保留日志与数据库中的可追溯根因；本轮未修改生产代码。
- 修复状态：已按 TDD 修复并现场复测；页面与 `collection_tasks.message` 使用简洁中文，服务日志继续记录完整原始异常。

## 结论

本轮发现的 1 个 Important、1 个 Minor 已完成最小修复并通过自动测试与真实浏览器复测，未发现新的生产代码缺陷。后续最终环境验收已进一步确认：HDFS 持久运行、正式日期 21 条数据、数据查询分页、KMeans、爆款预测、Apriori、知识库加载以及 Spark 四组 ECharts 图表均可真实运行；B站网络已恢复且历史真实采集成功，最终轻量检查为 HTTP 200，偶发 HTTP 412 仍按公开接口风控边界处理。

历史“未验证”章节保留的是首次问题发现时的现场边界，用于追溯当时为何不能声称通过；它不覆盖上述后续最终验证结论。管理员采集与手动清洗仍保持独立操作，失败不会伪装成功，也不会生成假数据。
