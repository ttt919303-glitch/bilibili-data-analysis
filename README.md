# 基于哔哩哔哩视频数据的数据分析与 AI 知识库系统

当前已完成第三阶段：在第二阶段基础上增加 pandas 数据清洗，并保留原始与清洗后 CSV 供答辩展示。

## 启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

浏览器访问 `http://127.0.0.1:5052/login`。项目默认使用 5052 端口，避免与当前电脑上已占用 5000 端口的旧服务冲突。

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | admin | admin123 |
| 普通用户 | user | user123 |

## 测试

```powershell
..\.venv\Scripts\python.exe -m pytest tests -v
```

首次启动会自动创建 `instance/users.db`，并使用 Werkzeug 哈希方式保存两个账户密码。

## 自动采集并生成 CSV

管理员登录后进入“数据管理”，输入关键词和数量，点击“浏览器采集（推荐）”或“API采集（备用）”。程序会自动爬取并将结果追加保存到 `data/videos.csv`，同时记录每条数据的采集日期，不需要先上传 CSV 文件；首页统计会重新读取该文件计算。

页面保留“可选：导入已有 CSV”入口，仅用于导入外部数据。CSV 至少包含 `title`、`up_name`、`play_count`、`like_count`；也支持“标题、UP主、播放量、点赞”等常见中文列名。

## 数据清洗

管理员在“数据管理”点击“开始数据清洗”后，原始数据 `data/videos.csv` 保持不变，清洗结果写入 `data/videos_cleaned.csv`。首页与数据列表会优先读取清洗数据；清洗文件不存在时才读取原始数据。

## HDFS 最小存储

管理员可将 `data/videos_cleaned.csv` 上传到 `/bilibili/videos_cleaned.csv`，并读取前 5 行验证结果。程序优先通过 WebHDFS 连接课程 Ubuntu Hadoop（默认 `http://192.168.8.140:50070`，用户 `tan`），也保留本机 `hdfs dfs` 作为备用；环境不同可设置 `HDFS_WEB_URL`、`HDFS_WEB_USER` 或 `HDFS_CMD`。HDFS 未启动时只显示不可用提示，不影响登录、导入和清洗功能。

启动课程虚拟机后，在 Ubuntu 中执行 `start-dfs.sh`，用 `jps` 确认 `NameNode`、`DataNode` 和 `SecondaryNameNode` 均在运行；如果 WebHDFS 地址不同，请在启动 Flask 前覆盖环境变量：

```powershell
$env:HDFS_WEB_URL = "http://<NameNode地址>:50070"
$env:HDFS_WEB_USER = "<HDFS用户>"
python app.py
```

## Playwright 浏览器采集

推荐由管理员在“数据管理”中使用“浏览器采集（推荐）”：项目通过 Playwright 控制项目独立的 Microsoft Edge 持久化会话，先从 B 站正常搜索页面取得视频，再由同一次采集任务自动访问详情页并同步播放、点赞、投币、收藏和分享，全部写入 `data/videos.csv` 后才返回结果。浏览器模式支持每次 1~200 条，建议采集 50~200 条；API 采集仍保留为备用方式，并保持自己的原有限额。

如需登录，先运行下面的诊断命令，并在弹出的项目专用 Edge 中手动登录 B 站；关闭浏览器后，登录状态仅保存于项目的 `browser_data/`，该目录已被 Git 忽略。项目不会读取默认 Edge/Chrome Profile、Cookie 或浏览器密码，也不会要求导出 Cookie。

```powershell
..\.venv\Scripts\python.exe -m pip install playwright
..\.venv\Scripts\python.exe debug_browser_crawler.py --browser msedge
```

启动 Flask 后，管理员输入关键词和数量，点击“浏览器采集（推荐）”即可开始；搜索和详情互动字段由同一个任务完成，不需要再手工回填。采集结束只会返回数据管理页面，不会自动触发清洗、HDFS、Spark、数据挖掘或 QA。

## 浏览器互动数据回填

“修复历史互动数据（50条）”仅用于处理旧版本已经写入但缺少互动字段的数据；新浏览器采集会在同一次任务中自动完成详情字段。每批最多处理 50 个不同的视频链接，断点和短失败摘要保存在本地 `data/interaction_backfill_state.json`，便于异常后继续；状态文件不包含 Cookie、账号、完整异常或页面 HTML，且不会提交到 Git。

单个视频遇到人工验证、页面结构异常或超时时会先记录并跳过，所有新链接完成后再有限重试，单个链接最多尝试 3 次；连续两个页面要求安全验证时会触发熔断并停止，不会自动处理验证码。旧式 AV 链接会在回填模块内规范化为 HTTPS，课程 season 链接会明确记录为不支持。回填只更新 `data/videos.csv`，不会自动清洗或触发 HDFS、Spark、挖掘和 QA；如需在“清洗数据”视图看到新数值，请管理员随后手动执行一次数据清洗。

需要连续处理所有待回填链接时，运行下面的命令。命令仍按每批 50 条顺序访问，输出每批 JSON 进度并从状态文件恢复；出现连续安全验证或所有失败链接达到重试上限后会明确停止。

```powershell
..\.venv\Scripts\python.exe run_interaction_backfill.py
```

若首轮结束后仍有普通 BV/AV 因临时超时或结构问题达到 3 次上限，可显式运行 `..\.venv\Scripts\python.exe run_interaction_backfill.py --retry-exhausted` 开启一个新的有限重试周期；该参数不会重试不属于普通视频详情页的课程 season URL。

可先运行以下只读命令确认当前详情页互动字段：

```powershell
..\.venv\Scripts\python.exe debug_browser_interactions.py --browser msedge
```

