# 基于多技术栈的数据分析与 AI 知识库构建设计说明

## 1. 项目定位

本项目是普通本科《大数据开发综合实践》课程作业，目标是在单机环境中完成真实 B 站公开数据采集、pandas 清洗、HDFS 存储、机器学习挖掘、Spark 分析、ECharts 可视化、LangChain 本地知识库、用户权限与定时采集，并以 Flask Web 页面完成演示。

项目只运行一个 Flask Python 进程。实现优先级依次为：能真实运行、能完整演示、符合课程要求、代码容易解释。禁止引入微服务、前后端分离、Docker、Kubernetes、Kafka、RabbitMQ、Celery、Redis 分布式锁、数据库锁和企业级分层。

## 2. 已确认的数据边界

系统不采集评论内容，也不采集评论数量。不得请求评论列表接口，不得读取视频详情中的 `stat.reply`，不得在任何存储、分析、知识库或页面中重新加入评论相关字段。

清洗后视频记录固定包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `bvid` | BV 号，单日数据的去重键 |
| `title` | 视频标题 |
| `video_url` | B 站视频地址 |
| `up_name` | UP 主名称 |
| `publish_time` | 视频发布时间，统一为 `YYYY-MM-DD HH:MM:SS` |
| `view_count` | 播放量，整数 |
| `like_count` | 点赞量，整数 |
| `coin_count` | 投币量，整数 |
| `favorite_count` | 收藏量，整数 |
| `share_count` | 分享量，整数 |
| `collect_date` | 数据快照/采集归属日期，统一为 `YYYY-MM-DD` |

字段名从采集器、pandas、HDFS、机器学习、Spark、知识库到模板保持一致。

## 3. 总体架构

采用单体 Flask + Jinja2 + Bootstrap + ECharts：

- `app.py`：应用创建、登录与权限、页面路由、采集 API、简单后台线程和任务状态。
- `config.py`：MySQL、WebHDFS、Spark、Flask session、采集参数和定时任务配置。
- `collector/bilibili_collector.py`：B 站公开搜索、视频详情、重试、限速和字段映射。
- `services/hdfs_service.py`：按日期读取、合并、去重并写入 HDFS。
- `analysis/mining.py`：KMeans、爆款预测和 Apriori。
- `analysis/spark_analysis.py`：从 HDFS 读取并生成四组 TOP10 分析结果。
- `knowledge/qa.py`：LangChain Document、TF-IDF Retriever、本地知识库和结构化问题回答。
- `scheduler/jobs.py`：APScheduler 每日采集任务，复用手动采集的同一业务入口。
- `templates/` 与 `static/`：服务器渲染页面、样式、ECharts 和采集状态轮询。
- `sql/init.sql`：仅建立 `users` 和 `collection_tasks` 两张表，并初始化课程演示账户。

不继续拆分 Controller、DAO、DTO、VO、Repository 等企业目录。

## 4. 单机运行配置

默认面向单机本地演示环境：

- MySQL：`localhost:3306`
- WebHDFS：`http://localhost:9870`
- Spark：`local[*]`
- Flask：`http://127.0.0.1:5000`

用户名、密码和服务地址通过环境变量覆盖。应用不在导入阶段主动连接外部服务，具体功能被调用时再建立连接并报告明确错误。

## 5. 用户与权限

MySQL 只保存系统用户和采集任务。

`users` 表字段：`id`、`username`、`password`、`role`。密码使用 Werkzeug 哈希，角色仅允许 `admin` 与 `user`。

`collection_tasks` 表字段：`id`、`keyword`、`target_count`、`success_count`、`status`、`collect_date`、`created_at`、`finished_at`、`message`。状态仅允许 `waiting`、`running`、`success`、`failed`。

任务成功写入 HDFS 至少 1 条数据时状态记为 `success`；如果 `success_count < target_count`，在 `message` 中说明目标数量和实际采集数量。采集到 0 条、整体采集失败或 HDFS 写入失败时状态记为 `failed`。不得新增 `partial` 或其他任务状态。

`/login` 验证账号并写入 Flask session，`/logout` 清除 session。管理员可进入 `/collect` 并调用 `/api/collect`；普通用户即使直接调用采集 API，也必须得到 HTTP 403。首页、数据查询、挖掘、Spark/可视化和知识库对已登录的两种角色开放。

## 6. 真实采集主链路

唯一采集链路如下：

1. 管理员打开 `/collect`，输入关键字、采集日期和目标数量。
2. 浏览器 `POST /api/collect`，后端校验权限和参数，在 MySQL 创建 `waiting` 任务并返回 `task_id`。
3. Flask 启动一个 Python `threading.Thread`，将任务改为 `running`。
4. 后台线程调用 `collector.bilibili_collector.collect(keyword, target_count, collect_date)`。
5. `search_videos(keyword, page)` 调用 B 站公开搜索接口并取得 BV 号。
6. `get_video_detail(bvid)` 调用公开视频详情接口，读取标题、链接、UP 主、发布时间以及 `view`、`like`、`coin`、`favorite`、`share`；明确忽略 `reply`。
7. 每个请求设置常规浏览器 User-Agent、Referer 和 timeout；请求间适当 sleep；网络失败或 5xx 最多重试三次。单个视频失败时记录警告并继续，搜索接口整体失败时任务失败。
8. `clean_video_data(data)` 使用 pandas 处理缺失值、数值转换、日期统一与 BV 号去重。
9. `save_to_hdfs(data, collect_date)` 自动写入 HDFS，无任何下载或上传 CSV 步骤。
10. 后台线程更新 `collection_tasks.success_count/status/finished_at/message`。
11. 页面每 2 秒调用 `GET /api/collect/status/<task_id>`，展示状态和成功数量；任务完成后读取并展示该归属日期最新的部分视频数据，不建立任务结果表，也不承诺这些记录严格等于本次任务的全部结果。

搜索或详情公开接口若返回验证码、HTTP 412、HTTP 429、非预期 JSON 或业务错误码，系统必须记录接口、HTTP 状态和响应摘要。只要至少 1 条真实数据成功写入 HDFS，任务状态就是 `success`，并在 `message` 中说明实际数量；0 条或整体失败才标记为 `failed`。不得生成随机数据，不得绕过网站安全机制。

采集器支持把目标数量设置为 10000 以上，并通过翻页累计采集；如果公开数据或接口限制导致实际数量不足，则保存实际成功结果并允许以后继续累计。

## 7. pandas 清洗

`clean_video_data(data)` 只接受第 2 节定义的固定字段，并执行：

- `bvid`、`title`、`video_url`、`up_name` 缺失时填充空字符串。
- 五个统计字段 `view_count`、`like_count`、`coin_count`、`favorite_count`、`share_count` 缺失时填充 0，并转换为非负整数。
- 接口返回整数时直接保留；仅对实际出现的字符串数量处理 `万` 和 `亿` 单位。
- `publish_time` 统一为 `YYYY-MM-DD HH:MM:SS`。
- `collect_date` 统一为 `YYYY-MM-DD`。
- 删除 `bvid` 为空的记录，并按 `bvid` 去重，保留最后一条有效记录。

清洗函数不吞掉结构错误；输入不是记录列表或缺少必要结构时直接抛出可定位的异常。

## 8. HDFS 存储与并发

HDFS 主目录固定为：

```text
/bigdata_course/bilibili/date=YYYY-MM-DD/videos.jsonl
```

`save_to_hdfs(data, date)` 先读取同日已有数据，与新数据合并后按 `bvid` 去重，再写入同日文件。`read_from_hdfs(date)` 只读取指定日期并返回固定字段记录。

项目只运行一个 Flask Python 进程，因此使用按日期管理的进程内 `threading.Lock` 保护同日“读取、合并、写回”临界区。不得增加 Redis 分布式锁、数据库锁或其他分布式组件。写入使用 HDFS 临时文件后重命名，避免进程中途失败破坏已存在的完整文件。

HDFS 连接失败时向页面返回“连接 HDFS 失败，请检查 Hadoop 是否启动”，同时日志保留原始异常；指定日期文件不存在时按“该日期暂无数据”处理，而不是伪造空统计结果。

## 9. 日期规则

除登录、退出和采集状态接口外，核心页面统一接收 `date=YYYY-MM-DD`。没有日期参数时使用服务器本地时区的昨天。

首页、数据查询、挖掘、Spark/可视化和知识库顶部使用同一种日期选择器。页面提交后把日期继续传给读取、分析、图表和问答函数，禁止某一层擅自改回当天或全量数据。

`collect_date` 表示数据快照/采集归属日期，不要求视频的 `publish_time` 等于 `collect_date`。采集任务的 `collect_date`、HDFS 分区日期、页面查询日期和分析日期使用同一个归属日期。

## 10. 数据挖掘

### 10.1 KMeans

KMeans 特征固定为：

- `like_count`
- `coin_count`
- `favorite_count`
- `share_count`

先使用 `StandardScaler` 标准化，再执行 `KMeans(n_clusters=3, random_state=42, n_init=10)`。根据各簇四项特征中心的总和从低到高映射为“低互动”“中互动”“高互动”，展示每簇视频数、平均播放量和平均点赞量。`view_count` 只可用于结果展示，不得作为聚类特征。

当有效样本少于 3 条时返回明确的“数据量不足，至少需要 3 条视频”提示。

### 10.2 爆款预测

当天 `view_count` 的 80% 分位数为爆款阈值，标签定义为：

```text
is_hot = view_count >= 当天 view_count 的 80% 分位数
```

预测特征固定为 `like_count`、`coin_count`、`favorite_count`、`share_count`。`view_count` 只产生标签，绝不能进入模型输入。

模型使用 `RandomForestClassifier(random_state=42)`。数据满足分层划分条件时使用 `train_test_split(..., stratify=y, random_state=42)`，输出阈值、accuracy、precision、recall、classification report 和逐视频预测结果。数据不足或标签只有一类时显示原因，不伪造模型指标。

### 10.3 Apriori

对当天四项互动指标分别按中位数转换为：

- `high_like`
- `high_coin`
- `high_favorite`
- `high_share`

使用 mlxtend Apriori 和 `association_rules` 分析点赞、投币、收藏、分享之间的关联，展示 antecedents、consequents、support、confidence 和 lift。没有满足阈值的频繁项集或规则时返回空结果说明。

## 11. Spark 分布式分析与 ECharts

PySpark 从所选日期的 HDFS JSON Lines 读取数据，生成至少四项结果：

1. UP 主视频数量 TOP10。
2. 播放量最高的视频 TOP10。
3. 点赞量最高的视频 TOP10。
4. `like_count + coin_count + favorite_count + share_count` 综合互动最高的视频 TOP10。

分析结果转换为简单 Python 字典列表，通过 Flask 注入模板并交给 ECharts。可视化页使用两列卡片布局展示四张图，不制作商业大屏和复杂动画。Spark 或 Java 未启动时页面显示“Spark 分析失败，请检查 Spark 和 Java 环境”，日志保留根因。

## 12. AI 本地知识库

`knowledge/qa.py` 从所选日期 HDFS 数据建立 LangChain `Document` 列表，每条文档包含视频标题、UP 主、播放量、点赞量、投币量、收藏量和分享量。使用 LangChain TF-IDF Retriever 构建无需联网 API 的本地向量检索。

以下三类课程指定问题使用 pandas 对当天真实数据做确定性统计，并把答案组织为自然语言：

- 哪个 UP 主视频最多。
- 播放量最高的视频是哪个。
- 哪些视频点赞或投币最高。

其他问题先通过 Retriever 返回最相关的真实视频信息。知识库构建失败时页面显示明确错误，不能导致整个 Flask 网站崩溃；不得调用未配置的在线 LLM，也不得编造回答。

## 13. 自动采集

APScheduler 在每天 00:10 触发 `collect_yesterday_data()`，日期取服务器本地时区的昨天，关键字使用配置项 `DEFAULT_KEYWORD`。自动任务创建同样的 `collection_tasks` 记录，并调用与手动采集完全相同的采集、清洗和 HDFS 写入函数；任务运行时采集到的视频统一归档到昨天的 HDFS 日期分区，不按视频发布时间重新分区。

关闭 Flask debug reloader，或确保调度器只在实际服务进程中启动，避免开发重载导致每日任务注册两次。

## 14. 页面设计

页面使用 Bootstrap、少量原生 CSS、Jinja2 和 ECharts，采用白色背景与简单蓝色主题。

- `/login`：用户名、密码和错误提示。
- `/`：昨日或所选日期的四个统计卡片、热门视频 TOP5 和模块入口。
- `/collect`：管理员采集表单、任务状态、进度和该归属日期最新部分视频表格。
- `/data`：日期、标题/UP 主关键字搜索、分页和视频链接。
- `/mining`：KMeans、爆款预测和 Apriori 结果。
- `/visualization`：四张 Spark/ECharts 图。
- `/knowledge`：日期、问题输入框和基于真实数据的回答。

导航栏根据 session 角色决定是否显示“数据采集”，但后端权限检查仍是最终安全边界。任何页面都不提供 CSV 上传入口。

## 15. 错误处理、日志与可追踪性

使用 Python `logging`，在以下关键节点记录任务 ID、日期、关键字和结果数量：任务创建、采集开始、每页搜索、单视频详情失败、清洗前后数量、HDFS 合并前后数量、任务完成或失败、Spark 分析和知识库构建。

异常处理遵循 Fail Fast：只在能够补充上下文或隔离单个视频失败的边界捕获异常，不使用宽泛兜底返回假成功，不静默吞错。页面展示适合课程演示的简洁错误，日志保留原始异常堆栈和接口响应摘要。

## 16. 测试与验收

测试分为不依赖外部服务的自动测试和依赖本地课程环境的真实联调。

自动测试覆盖：

- 管理员与普通用户登录、session 和 403 权限。
- 采集 API 确实调用 `collect()`，而不是读取本地文件。
- 搜索和详情响应到 11 个固定字段的映射，并验证完全没有评论字段。
- pandas 数值、日期、缺失值和 BV 去重。
- HDFS 服务的日期路径、合并去重、临时文件重命名和进程内日期锁。
- 任务至少写入 1 条即为 `success`，不足目标数量时 `message` 记录实际数量；0 条或写入失败为 `failed`。
- 所有页面默认昨天以及显式日期贯穿。
- `collect_date` 只决定快照归属和 HDFS 分区，不过滤或改写 `publish_time`。
- KMeans 特征仅四项互动指标。
- 爆款标签使用播放量 80% 分位数，模型输入不含 `view_count`。
- Apriori 仅使用四个 `high_*` 变量。
- Spark 四项分析字段与 ECharts 数据结构一致。
- 三类知识库问题从真实记录得到确定性回答。
- 模板、路由和 JavaScript API 地址一致，项目中不存在 CSV 上传功能。

真实联调覆盖：

- 使用管理员账号从网页发起小批量真实采集。
- 记录 B 站搜索与详情接口的 HTTP 状态、业务码和实际返回结构。
- 验证播放、点赞、投币、收藏和分享来自详情接口真实字段。
- 验证 WebHDFS 中出现对应日期的 `videos.jsonl`。
- 验证数据查询、挖掘、Spark 图表和知识库使用刚采集的数据。

当前开发机仅检测到 Python，未检测到 `java`、`hdfs`、`spark-submit` 和 `mysql` 命令。因此可先完成自动测试与公开接口验证；MySQL、HDFS 和 Spark 的真实联调必须在这些服务安装并启动后执行，未实际执行的项目不得声称已经通过。

## 17. 分阶段交付

1. 项目骨架、配置、MySQL 表、登录与权限。
2. 真实 B 站采集、pandas 清洗、WebHDFS 写入、任务线程、状态轮询与采集页面。
3. 数据查询、首页统计、统一日期选择。
4. KMeans、爆款预测和 Apriori。
5. Spark 四项分析与 ECharts。
6. LangChain 本地知识库。
7. APScheduler 每日任务。
8. 全链路测试、README 和过度工程化清理。

每一阶段必须先写可验证测试，再实现最小代码，并检查字段、路由、模板和日期参数的一致性后才能进入下一阶段。
