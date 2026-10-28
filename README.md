# B 站视频数据分析课程项目

## 1. 项目介绍与课程模块对应关系

本项目以 B 站视频为数据源，完成“采集、存储、清洗、分析、展示、问答”的课程实践闭环。管理员从网页发起采集后，原始数据先写入 HDFS；管理员再按日期手动运行 pandas 清洗并生成正式数据。普通用户可查询正式数据、查看传统数据挖掘结果、运行 Spark 可视化，并通过本地 TF-IDF 知识库提问。

| 课程模块 | 项目实现 |
| --- | --- |
| 数据采集 | B 站关键词搜索与视频详情接口 |
| Web 与权限 | Flask 页面、会话登录、管理员采集/清洗权限 |
| 关系型数据库 | MySQL 用户与采集任务状态 |
| 分布式存储 | HDFS JSON Lines 日期目录 |
| 数据清洗 | pandas 统一 11 个视频字段 |
| 数据挖掘 | KMeans、爆款预测、Apriori |
| 大数据分析 | Spark DataFrame TOP10 统计与 ECharts 图表 |
| 知识库 | 规则问答与本地 TF-IDF 检索 |
| 定时任务 | APScheduler 每天 00:10 只采集前一天原始数据 |

## 2. Python 3.8+、Hadoop 3.x、Spark 3.x、MySQL 8.0 环境

需要 Python 3.8+、MySQL 8.0、Hadoop 3.x/HDFS，以及用于可视化分析的 Spark 3.x。Python 依赖见 `requirements.txt`。

运行项目需要可用的 MySQL、Hadoop/HDFS、Java 与 Spark 环境；首次部署应按下文设置环境变量，并确认各服务能从 Flask 进程所在环境访问。

## 3. 精简项目目录

```text
app.py                    Flask 路由、登录和采集任务编排
collector/                B 站采集与 pandas 清洗
services/                 WebHDFS 读写
analysis/                 KMeans、爆款预测、Apriori、Spark 分析
knowledge/                本地 TF-IDF 知识库问答
scheduler/                每日采集调度
templates/ static/        网页模板、样式与轮询脚本
sql/init.sql              MySQL 建表
tests/                    自动化测试
```

## 4. MySQL 初始化与登录账号

在项目根目录执行：

```bash
mysql -u root -p < sql/init.sql
```

初始化会创建 `bigdata_course`、`users` 和 `collection_tasks`。Flask 首次启动时，会根据 `ADMIN_USERNAME`、`ADMIN_PASSWORD`、`USER_USERNAME` 和 `USER_PASSWORD` 创建管理员与普通用户；口令只从本地环境或未提交的 `.env` 文件读取，并以 Werkzeug 哈希形式写入 MySQL。

## 5. 启动 HDFS 与检查课程目录

常见 Linux 单机环境可启动 HDFS 后检查目录：

```bash
start-dfs.sh
hdfs dfs -ls /bigdata_course/bilibili
```

Windows 中若 Hadoop 已安装并配置到 PATH，可使用：

```bat
start-dfs.cmd
hdfs dfs -ls /bigdata_course/bilibili
```

如果 HDFS 由 systemd 管理，可在对应环境启动服务后运行以下只读检查命令：

```bash
systemctl --user start hdfs-namenode.service hdfs-datanode.service
source ~/.bigdata_course_env
jps
hdfs dfsadmin -report
hdfs dfs -ls /bigdata_course/bilibili
```

不要执行 `hdfs namenode -format`，它会破坏已有 HDFS 元数据。

## 6. WebHDFS 9870、NameNode RPC 9000 与日期目录

默认 WebHDFS 地址为 `http://127.0.0.1:9870`，NameNode RPC 地址为 `hdfs://127.0.0.1:9000`。同一日期目录分别保存原始数据与正式数据：

```text
/bigdata_course/bilibili/date=YYYY-MM-DD/videos_raw.jsonl
/bigdata_course/bilibili/date=YYYY-MM-DD/videos.jsonl
```

网页手动采集和定时采集都只写 `videos_raw.jsonl`，不会自动覆盖正式数据；管理员专用的 `/api/clean` 读取指定日期的原始数据，清洗后写入 `videos.jsonl`。升级前已经存在的 `videos.jsonl` 正式历史数据仍可继续用于查询和分析。每条 JSON Lines 记录固定保留 `bvid`、`title`、`video_url`、`up_name`、`publish_time`、`view_count`、`like_count`、`coin_count`、`favorite_count`、`share_count`、`collect_date` 这 11 个字段。

页面默认日期和定时采集日期均为服务器“昨天”。管理员可以反复选择同一个数据归属日期并使用不同的自定义关键词，把新 BV 累计到同一份 `videos_raw.jsonl`；不同日期的数据集和进度彼此独立，不会自动合并。

## 7. Java、spark-submit --version 与 local[*]

Spark 分析需要 Java 与 Spark 安装在启动 Flask 的同一环境。安装后先确认：

```bash
java -version
spark-submit --version
```

默认 `SPARK_MASTER=local[*]`，表示本地 Spark 使用可用 CPU 核心。部署后先验证 Java、Spark 与 HDFS 连通性；分析页面只展示本次从正式数据运行得到的结果。

## 8. Python 虚拟环境与依赖安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 9. 环境变量与启动 Flask

启动前必须设置 `SECRET_KEY`、`MYSQL_PASSWORD` 以及两组用户的 `ADMIN_USERNAME`、`ADMIN_PASSWORD`、`USER_USERNAME`、`USER_PASSWORD`。请为管理员与普通用户设置不同用户名和强口令。仓库不提供这些值的默认值；其余可按需要设置：`MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_DATABASE`、`HDFS_WEB_URL`、`HDFS_NAMENODE_URI`、`HDFS_USER`、`SPARK_MASTER`、`DEFAULT_KEYWORD`、`DEFAULT_TARGET_COUNT`、`COURSE_DATASET_TARGET`、`ENABLE_SCHEDULER`。`COURSE_DATASET_TARGET` 默认是 `10000`，只影响所选日期的课程进度显示，不会改变单次任务语义。

示例（PowerShell）：

```powershell
$env:MYSQL_PASSWORD = "你的MySQL密码"
$env:SECRET_KEY = "请替换为随机长字符串"
$env:ADMIN_USERNAME = "管理员用户名"
$env:ADMIN_PASSWORD = "管理员强口令"
$env:USER_USERNAME = "普通用户名"
$env:USER_PASSWORD = "普通用户强口令"
$env:HDFS_WEB_URL = "http://127.0.0.1:9870"
$env:HDFS_NAMENODE_URI = "hdfs://127.0.0.1:9000"
python app.py
```

示例（Linux）：

```bash
export MYSQL_PASSWORD='你的MySQL密码'
export SECRET_KEY='请替换为随机长字符串'
export ADMIN_USERNAME='管理员用户名'
export ADMIN_PASSWORD='管理员强口令'
export USER_USERNAME='普通用户名'
export USER_PASSWORD='普通用户强口令'
export HDFS_WEB_URL='http://127.0.0.1:9870'
export HDFS_NAMENODE_URI='hdfs://127.0.0.1:9000'
python app.py
```

浏览器访问 `http://127.0.0.1:5000`。

## 10. 管理员采集 20 条的完整网页演示步骤

1. 使用配置的 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 登录。
2. 打开“数据采集”，自由输入关键词“`大数据技术`”，选择数据归属日期，“本次希望新增数量”填写 `20`。该数量表示本次最多新增 20 个当前 raw 数据集中尚不存在的不同 BV，不是课程数据集总目标。
3. 点击“开始采集”，网页会轮询任务状态，依次可见 `waiting`、`running`，最终为 `success` 或 `failed`。
4. 成功时确认采集前已有、本次实际新增、当前原始数据总量和“最新原始采集数据”表；再用 HDFS 命令检查相应 `date=YYYY-MM-DD/videos_raw.jsonl`。此时正式数据尚未改变。
5. 可保持同一个数据归属日期，依次使用 `Spark`、`Hadoop` 等管理员自定义关键词继续累计；每次都从搜索第 1 页开始，并在请求详情前排除同日期 raw 中已有的 BV。
6. 达到课程目标后仍可继续采集；页面显示真实数量与完成度，进度条视觉宽度封顶 100%。
7. 在同一页面确认清洗日期后点击“开始数据清洗”，核对清洗前、清洗后、删除/去重数量和清洗状态，再检查相应 `date=YYYY-MM-DD/videos.jsonl`。
8. 打开 `/data?date=YYYY-MM-DD` 查看该日期的正式数据；数据查询、挖掘、Spark 和知识库始终读取 `videos.jsonl`。
9. 采集完全使用网页与 B 站接口，**不上传 CSV**。公开接口受限时必须保留实际新增数量；0 条新增应标记失败，不能生成假数据。

```text
开始采集 -> videos_raw.jsonl -> 页面显示最新10条原始数据
开始数据清洗 -> pandas clean_video_data() -> videos.jsonl
数据查询/挖掘/Spark/知识库 -> videos.jsonl
```

为避免公开接口限流或请求时间过长，首次联调建议先将“本次希望新增数量”设为 1，确认端到端链路后再演示 20 条。

## 11. 数据查询、KMeans、爆款预测、Apriori、四张 Spark 图演示

普通用户或管理员登录后可按日期使用以下页面：

- `/data`：按标题或 UP 主关键字查询、分页查看 HDFS 数据。
- `/mining`：展示 KMeans 三类互动聚类、随机森林爆款预测和 Apriori 关联规则；数据量不足时页面会说明对应算法不可用的原因。
- `/visualization`：在 Java、Spark 与 HDFS 均可用时显示四张 Spark ECharts 图，分别为 UP 主视频数量 TOP10、播放量 TOP10、点赞数 TOP10、互动量 TOP10。

## 12. AI 知识库三类问题演示

打开 `/knowledge` 并选择已采集日期，可依次输入：

```text
哪个UP主视频最多？
播放量最高的视频是哪个？
哪些视频点赞投币最高？
```

前两类问题由本地数据统计精确回答；第三类会分别返回点赞和投币最高的视频。其他问题使用本地 TF-IDF Retriever 返回相关视频资料。回答中的标题、UP 主和统计值都应回到同日期 HDFS JSON Lines 复核。

## 13. HDFS/MySQL/Spark/B 站接口错误检查方法

HDFS：执行 `jps`、`hdfs dfsadmin -report`、`hdfs dfs -ls /bigdata_course/bilibili`；确认 NameNode、DataNode 和一个 Live DataNode，再检查端口 9870/9000。若服务未启动，请按部署环境的服务管理方式启动；禁止重新格式化 NameNode。

MySQL：用 `mysql -u root -p -e "USE bigdata_course; SELECT id, status, success_count, collect_date, message FROM collection_tasks ORDER BY id DESC;"` 检查任务记录与失败原因。

Spark：先运行 `java -version` 与 `spark-submit --version`，再访问 `/visualization?date=YYYY-MM-DD`。缺少 Java、Spark 或 HDFS 时，页面和 Flask 日志会提供明确错误边界。

B 站接口：查看 Flask 日志中的任务 ID、关键词、日期、HTTP 状态和 B 站业务码；如遇限流、网络错误或空结果，应如实保留 `failed` 状态和消息，不应重试到失去可观测性或改用本地假数据。

自动定时任务每天只采集 raw 数据并写入 `videos_raw.jsonl`，不会自动执行 pandas 清洗。正式数据清洗只能由管理员在“数据采集”页面手动点击；采集与清洗是两个独立操作。

## 14. 已知边界

公开接口存在访问频率与数据可用性限制，采集成功时保存本次实际新增数量，新增 0 条时任务失败；项目绝不生成假数据。HTTP 412 等限流响应属于公开接口边界，不使用代理池、Cookie 池、验证码或其他方式绕过，也不修改采集代码掩盖它。

数据采集页面的课程进度只统计所选日期 `videos_raw.jsonl` 中不同的非空 BV，最新数据表只展示该日期最近最多 10 条原始记录；完整数量以上方统计为准。首页、数据查询、挖掘、Spark 和知识库始终读取管理员手动清洗后生成的 `videos.jsonl`。
