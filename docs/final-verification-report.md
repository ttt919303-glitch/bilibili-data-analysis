# 课程项目最终验收报告

## 1. 验收范围与 Git 基线

- 验收日期：2026-08-13（Asia/Shanghai）
- 分支：`main`
- 本轮开始 HEAD：`993ed95`
- 最终交付提交：由交付后的 `git log -1` 唯一标识；提交哈希不在提交自身内容中自引用。
- Git 状态：全部交付文件提交后复查为 clean；最终哈希与状态同时在交付回执中记录。
- 范围：最终文档同步、一个过时 Spark 测试环境探测修正、已授权的 HDFS 降级与采集错误消息修复，以及去除交付包中的配置明文敏感值；未增加业务功能或重构冻结模块。

## 2. Python 自动测试

执行 `python -m pytest -q -rs`：`96 passed, 0 skipped, 1 warning`，退出码 0。唯一警告来自 joblib 无法读取物理核心数后改用逻辑核心，不影响测试结果。

## 3. 跳过项说明

最终没有跳过项。原跳过测试为 `tests/test_spark_analysis.py::test_four_spark_analyses_have_expected_order`，原因是测试只使用 `shutil.which("java")` 检测 PATH，而本机 Java 由有效 `JAVA_HOME` 提供；测试探测改为同时接受 `JAVA_HOME/bin/java.exe` 后，真实 Spark 集成测试通过，未修改生产 Spark 代码。

## 4. Node、编译、差异与禁用项验证

- Node 完整测试：`7 passed, 0 failed`。
- `python -m compileall -q -f ...`：通过。
- `tests/test_project_contract.py`：`4 passed`。
- `git diff --check`：通过。
- 生产目录扫描未发现评论字段或评论内容采集、`stat.reply`、CSV 上传/读写、Docker、Kafka、Celery、RabbitMQ 或 Redis 分布式锁实现。

## 5. MySQL 现场状态

MySQL `8.0.41` 可连接；数据库为 `bigdata_course`，必需表 `users`、`collection_tasks` 均存在。仓库不再内置 MySQL 口令和 Flask 密钥，当前机器通过用户环境变量提供，交付包不包含实际值。

## 6. HDFS 现场状态

- Hadoop `3.4.3`。
- `hdfs-namenode.service` 与 `hdfs-datanode.service` 均为 `active`。
- `hdfs dfsadmin -report` 显示 `Live datanodes (1)`，节点为 `127.0.0.1:9866`，Missing/Corrupt blocks 为 0。
- Windows WebHDFS 返回 `{"Path":"/user/dr.who"}`。
- `/bigdata_course/bilibili/date=2026-08-09` 存在，共 1 个正式文件、7376 字节；未格式化、删除或伪造 HDFS 数据。
- 当前 WSL 用户 `Linger=yes`，登录计划任务负责维持现有 HDFS 服务，不要求课堂演示时保留可见终端。

## 7. Java 与 Spark 现场状态

Windows Java 为 OpenJDK/JBR `21.0.8`；WSL Java 为 OpenJDK `17.0.20`；`spark-submit --version` 返回 Spark `3.5.1`、Scala `2.12.18`、Java `21.0.8`。Spark 本地集成测试和真实 HDFS 日期分析均已运行，不是仅做静态检查。

## 8. 浏览器端到端复核

使用浏览器插件以 `student` 登录并访问正式日期 `2026-08-09`：

- `/`：读取 21 条正式 HDFS 数据；首页统计与 TOP 视频正常显示。
- `/data`：表格、标题/UP 主搜索、分页和视频链接正常；第一页显示 20 条，共 2 页。
- `/mining`：KMeans 三类、爆款预测和 Apriori 结果正常显示。
- `/visualization`：UP 主视频数量、播放量、点赞数、互动量四组 ECharts 图表正常显示。
- `/knowledge`：本地知识库页面和正式日期数据正常加载。

管理员 `/collect` 页面可打开，采集与手动清洗入口彼此独立；对仅有正式数据、没有原始文件的 `2026-08-09` 点击清洗时，页面如实返回“该日期暂无原始采集数据”，没有伪造成清洗成功。

## 9. B 站轻量验证与外部限制

最终只进行一次轻量公开接口请求，返回 HTTP 200 与 JSON；没有做 21 条批量采集，也没有持续重试。随后唯一一次 `target_count=1` 的真实网页任务保持 `failed`、`success_count=0`，页面和数据库只显示简洁中文失败提示；考虑公开接口可能出现短时 HTTP 412 风控，本轮未绕过、未用代理池/Cookie 池/验证码，也未改采集逻辑。

## 10. 手动清洗数据流

课程数据流保持为：网页或每天 00:10 的 APScheduler 任务只写 `videos_raw.jsonl`；管理员按同一日期手动调用 pandas `clean_video_data()` 后才写 `videos.jsonl`。首页、数据查询、KMeans、爆款预测、Apriori、Spark 和知识库只消费正式文件；本轮没有因缺少新 raw 输入而制造清洗成功证据。

## 11. 课程要求映射

| 要求 | 最终实现与证据 |
| --- | --- |
| Flask | 登录、首页、采集、查询、挖掘、可视化、知识库页面与 API |
| 登录与管理员权限 | 会话登录；采集、清洗仅管理员可执行，普通用户接口返回 403 |
| B 站采集 | 关键词搜索、详情、分页与去重；真实失败保持 `failed/0` |
| pandas 手动清洗 | raw 读取、11 字段清洗、管理员主动写正式文件 |
| HDFS | WebHDFS 日期目录、raw/正式文件分离、一个 Live DataNode |
| 数据挖掘 | KMeans 三类、随机森林爆款预测、Apriori |
| Spark 与 ECharts | 四组 TOP10 Spark 分析并由四张 ECharts 图展示 |
| 本地知识库 | 规则统计问答与 LangChain TF-IDF Retriever |
| 调度器 | 每天 00:10 采集服务器昨天的 raw 数据，`max_instances=1` |
| 日期语义 | 页面默认昨天；采集、清洗、读取均使用明确的同一日期目录 |

## 12. 已修复问题复核

- HDFS 连接失败时 `/`、`/data`、`/mining` 返回正常课程页面与明确 HDFS 提示；首页不展示伪统计，数据表为空，挖掘算法不继续执行；正常无文件仍与连接失败区分。
- B 站或 HDFS 采集失败时，任务语义保持 `failed/0`，用户消息为简洁中文；完整原始异常通过 `logger.exception` 保留在服务日志。
- 配置不再把数据库口令或固定 Flask 密钥写入源码，缺少 `SECRET_KEY` 时启动会 fail fast。

## 13. 最终结论

本轮未发现新的可复现生产代码缺陷。当前唯一真实边界是 B 站公开接口的短时风控与网络波动；系统会如实失败、保留日志且不生成假数据。项目已达到课程提交状态，建议停止修改业务代码。
