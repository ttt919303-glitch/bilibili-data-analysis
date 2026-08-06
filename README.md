# 基于哔哩哔哩视频数据的数据分析与本地 AI 知识库系统

课程项目使用 Flask、Pandas、HDFS、PySpark、scikit-learn、mlxtend、Playwright、LangChain 和 ECharts。Windows 本机运行 Flask/Playwright/Spark Local Mode，课程 Ubuntu 虚拟机运行 Hadoop；不需要 OpenAI API Key、付费模型、Celery、Redis 或 Docker。

## 安装依赖

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Playwright 使用本机 Microsoft Edge 的项目独立会话；无需导出浏览器 Cookie，也不会读取系统默认浏览器 Profile。

## 启动 Flask

```powershell
.\venv\Scripts\python.exe app.py
```

访问 `http://127.0.0.1:5052/login`。默认端口仍为 `5052`。

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin123` |
| 普通用户 | `user` | `user123` |

首次启动会创建 `instance/users.db`，密码使用 Werkzeug 哈希保存。

## Hadoop、HDFS 上传与读取

在 Ubuntu 虚拟机中启动 Hadoop：

```bash
start-dfs.sh
jps
hdfs dfs -ls /
```

`jps` 应看到 NameNode、DataNode 和 SecondaryNameNode。Windows 启动 Flask 前可设置：

```powershell
$env:HDFS_WEB_URL = "http://192.168.8.140:50070"
$env:HDFS_WEB_USER = "tan"
$env:HDFS_CMD = "hdfs"
```

管理员在“数据管理”中可上传清洗 CSV 到 `/bilibili/videos_cleaned.csv` 并读取前 5 行验证。系统分析读取顺序统一为：

1. 配置 `HDFS_WEB_URL` 时通过 WebHDFS `OPEN` 读取完整 CSV；
2. 未配置 WebHDFS 时执行 `hdfs dfs -cat /bilibili/videos_cleaned.csv`；
3. HDFS 不可用时回退 `data/videos_cleaned.csv`；
4. 清洗 CSV 也不可用时回退 `data/videos.csv`。

页面会显示实际来源以及是否发生本地回退，不会把本地数据伪装为 HDFS 数据。

## 采集与自动清洗流水线

管理员在“数据管理”输入关键词和数量，可选择：

- “浏览器采集（推荐）”：Playwright 打开项目独立 Edge 会话，采集搜索结果与详情互动数据；
- “API采集（备用）”：使用现有 B 站公开搜索接口；
- “修复历史互动数据（50条）”：补全旧数据的互动指标。

成功写入原始 CSV 后会自动执行：

```text
采集/导入 -> 原子追加 data/videos.csv -> Pandas 清洗
-> 原子替换 data/videos_cleaned.csv -> 尝试上传 HDFS
```

HDFS 上传失败只记录警告，本地原始数据和清洗数据仍保留。进程内共享锁避免浏览器采集、API 采集、回填和每日任务同时修改 CSV。

如需先建立浏览器登录状态或诊断页面：

```powershell
.\venv\Scripts\python.exe debug_browser_crawler.py --browser msedge
.\venv\Scripts\python.exe debug_browser_interactions.py --browser msedge
```

## 日期选择

首页、数据管理、Spark、Spark API、数据挖掘和知识库均接受 `date=YYYY-MM-DD`，业务日期字段为 `publish_time`。页面日期框可直接切换；表单提交和页面导航会保留已选日期。

没有传日期时，系统按 `Asia/Shanghai` 取昨天；可用 `APP_TIMEZONE` 覆盖。非法日期返回友好的 400 页面。所有业务页始终严格按 `publish_time` 筛选，选中日期无数据时显示“该日期暂无数据”。

Spark API 示例：

```text
GET http://127.0.0.1:5052/api/spark/analysis?date=2026-08-06
```

## LangChain 本地知识库

知识库流程为：

```text
统一 HDFS/本地数据源 -> publish_time 日期切片
-> LangChain Document -> RecursiveCharacterTextSplitter
-> scikit-learn TF-IDF Embeddings 适配器
-> LangChain InMemoryVectorStore -> Retriever -> 显示命中标题/来源
```

每个视频 Document 包含标题、UP主、链接、播放、点赞、投币、收藏、分享、评论和发布时间。无需 API Key，也不会在运行时下载大型模型。

索引工件保存在 `data/knowledge_base/<日期>/`。日期变化、数据来源或内容指纹变化、索引不存在时自动重建；目录已加入 `.gitignore`。视频总数、UP主最多、各指标最高、Top N 和标题关键词查询仍由 Pandas 精确计算，其他问题使用 LangChain Retriever。

## 每日 00:00 自动采集

配置示例见 `.env.example`。PowerShell 启动前可设置：

```powershell
$env:AUTO_CRAWL_ENABLED = "true"
$env:AUTO_CRAWL_KEYWORDS = "大数据,人工智能,Python"
$env:AUTO_CRAWL_LIMIT = "100"
$env:APP_TIMEZONE = "Asia/Shanghai"
.\venv\Scripts\python.exe app.py
```

APScheduler 每天 00:00 运行前一天任务，自动使用无需人工浏览器的 API 采集器。任务严格保留 `publish_time == 目标日期` 的结果，对规范化 `video_url` 去重，然后追加原始 CSV、清洗并尝试上传 HDFS。最近摘要保存在 `data/daily_pipeline_status.json`，管理员页面会显示执行时间、数量、清洗结果、HDFS 状态和错误摘要。
定时任务默认启用；只有明确设置 `AUTO_CRAWL_ENABLED=false` 时才停用。

答辩时管理员可点击“立即执行昨日任务”；该按钮与定时器调用同一个 `run_daily_pipeline`，普通用户访问会返回 403。pytest、Flask debug reloader 父进程和重复 `create_app` 不会重复启动调度器。

## 数据挖掘

聚类、预测模型、Apriori 与固定关联规则都只使用选中日期数据。页面固定展示：

- 高点赞 → 高投币；
- 高点赞 → 高收藏；
- 高投币 → 高分享。

每条显示 support、confidence、lift；无法形成有效规则时明确显示“当前数据下未形成有效规则”。

## 运行测试

测试只使用临时目录和 mock，不访问真实 B 站、不启动真实浏览器、不连接真实 HDFS、不下载模型：

```powershell
.\venv\Scripts\python.exe -m pytest tests -v
```

## 答辩演示顺序

1. 启动 Ubuntu Hadoop，用 `jps` 与 `hdfs dfs -ls /` 展示服务；
2. 启动 Flask，以管理员登录；
3. 选择一个有数据的日期，展示首页与数据管理来源；
4. 运行 API 或浏览器采集，展示自动清洗与 HDFS 尝试结果；
5. 验证 `/bilibili/videos_cleaned.csv`，切换 Spark、挖掘页面；
6. 在知识库提问精确统计和 Spark 推荐问题，展示 Retriever 命中标题；
7. 点击“立即执行昨日任务”，展示最近任务状态。

真实 B 站网络、Edge 页面结构、Windows 到 Ubuntu 的 WebHDFS 连通性以及本机 Java/PySpark 环境需要在答辩机器上单独验证；自动化测试不会声称这些外部环境已连通。
