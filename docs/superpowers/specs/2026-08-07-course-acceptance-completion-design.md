# 课程验收缺失项补全设计

## 目标与边界

在保留现有 Flask 单体结构、登录权限、两类采集器、CSV 清洗、HDFS、Spark、挖掘和页面风格的前提下，补齐统一数据源、业务日期、本地 LangChain 知识库、每日任务和采集后流水线。不得覆盖仓库现有 `data/videos.csv` 与 `data/videos_cleaned.csv`；所有新增测试仅使用临时目录和模拟外部系统。

## 方案选择

采用“统一 Pandas 数据入口 + 薄路由 + 独立服务模块”。另一种方案是让 Spark、挖掘和问答各自读取 HDFS 并各自筛日期，但会重复选源规则且容易出现页面口径不一致；也不采用任务队列或外部向量数据库，因为超出课程项目范围。

## 模块职责

- `date_utils.py`：解析 `YYYY-MM-DD`，默认按 `APP_TIMEZONE`（缺省 `Asia/Shanghai`）取昨天，并按 `publish_time` 筛选 DataFrame。
- `hdfs_utils.py`：通过 WebHDFS `OPEN` 或 `hdfs dfs -cat` 读取完整清洗 CSV；`load_analysis_dataframe(...)` 严格按 HDFS、清洗 CSV、原始 CSV 选源并返回明确来源。
- `knowledge_base.py`：把选中日期的每条视频转换为 LangChain `Document`，经文本切分后用 scikit-learn TF-IDF 实现 LangChain `Embeddings` 适配器和内存向量检索；索引元数据与文档快照写入 `data/knowledge_base/`。日期或源数据指纹变化时重建。精确统计仍由 Pandas 计算，语义问题通过 Retriever 返回命中标题和来源。
- `daily_pipeline.py`：串行执行多关键词 API 采集、按 `publish_time` 精确筛选、规范化 URL 去重、原子追加、清洗、HDFS 上传和 JSON 状态落盘。HDFS 失败记录错误但不回滚本地文件。
- `scheduler.py`：用 APScheduler 每天 00:00 触发同一个 `run_daily_pipeline`；测试、debug reloader 父进程和重复 `create_app` 均不重复启动。
- `app.py`：只做配置、鉴权、日期错误转换、调用服务和模板上下文组装；手动 API、浏览器采集及回填完成后复用同一个清洗上传后处理函数。

## 数据流

分析读取路径为 `HDFS -> 本地清洗 CSV -> 本地原始 CSV -> 日期筛选 -> 页面/Spark/挖掘/知识库`。采集写入路径为 `采集 -> 进程内共享锁 -> 原子追加原始 CSV -> 清洗到临时文件并替换 -> 尝试上传 HDFS -> 刷新后由统一入口读取`。页面与 POST 表单统一携带 `date`，无数据时展示“该日期暂无数据”。

## 错误与可观测性

非法日期由统一异常转为 400 友好页面，不产生 500。外部 B 站、浏览器、HDFS 错误保留现有可用数据并写日志；每日任务状态 JSON 记录执行时间、数量、清洗摘要、HDFS 状态和错误摘要。CSV 与状态 JSON 均先写同目录临时文件再原子替换。

## 测试策略

新增单元与 Flask 集成测试覆盖日期默认/校验/页面透传、HDFS 两种读取与回退、挖掘统一选源、Document/本地 Retriever/精确问答/日期索引隔离、每日任务筛选去重清洗与 HDFS 降级、调度器防重和管理员权限。所有外部网络、浏览器、HDFS 与大型模型行为均 mock；最后运行 `python -m pytest tests -v`，并确认原有测试仍通过。
