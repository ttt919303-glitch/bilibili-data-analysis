# 本机大数据课程环境配置与联调记录

记录时间：2026-08-10（Asia/Shanghai）
项目目录：课程项目根目录（交付文档不记录个人绝对路径）

## 1. 环境检查结果

| 项目 | 实际结果 | 状态 |
| --- | --- | --- |
| Windows | Windows 11 家庭中文版，版本 `10.0.26200`，Build `26200`，x64 | 已验证 |
| WSL | WSL `2.7.11.0`，内核 `6.18.33.2-2` | 已验证 |
| Linux 发行版 | Ubuntu `26.04 LTS (Resolute)`，WSL 2，默认用户 `tlt` | 已验证 |
| WSL 网络 | NAT，检查时地址为 `172.17.150.203`；Windows localhost 转发可用 | 已验证 |
| MySQL | MySQL `8.0.41`，数据库 `bigdata_course` 可连接 | 已验证 |
| 原 Windows Java | `JAVA_HOME` 指向 IntelliJ JBR 21，但 `java` 不在 Windows PATH | 仅记录，项目 HDFS 不使用 |
| 原 Hadoop | Windows 与 WSL 均无可用 `hadoop`、`hdfs` 命令；机器上的旧实验资料不是 Hadoop 安装目录 | 已验证，未改动旧目录 |
| 原端口 | 9000、9870 均未监听 | 已验证 |
| 项目 HDFS 配置 | `HDFS_WEB_URL=http://127.0.0.1:9870`；`HDFS_NAMENODE_URI=hdfs://127.0.0.1:9000`；`HDFS_USER=hadoop`；`SPARK_MASTER=local[*]` | 已核对 |

## 2. Java 配置

Ubuntu 26.04 软件源检查时只提供 OpenJDK 25。为避免使用过新的 Java，采用 Microsoft 官方 OpenJDK 17 LTS Linux x64 归档。

- Java：Microsoft Build of OpenJDK `17.0.20+8-LTS`
- `JAVA_HOME`：当前 WSL 用户目录下的 Java 17 软链接
- 实际目录：当前 WSL 用户目录下的 JDK 17.0.20+8
- 环境文件：`$HOME/.bigdata_course_env`

验证结果：

```text
openjdk version "17.0.20" 2026-07-21 LTS
javac 17.0.20
```

归档 SHA-256：

```text
69479b83a0e4408cc24d4dfb551db3759ba145ddce6131c6806a97d7bd8604cd
```

本地计算值与微软发布的 `.sha256sum.txt` 完全一致后才解压。

## 3. Hadoop 配置

- Hadoop：Apache Hadoop `3.4.3`
- `HADOOP_HOME`：当前 WSL 用户目录下的 Hadoop 软链接
- 实际目录：当前 WSL 用户目录下的 Hadoop 3.4.3
- 安装方式：普通用户目录解压，不使用 Docker、虚拟机、winutils、Kerberos 或多节点集群

Apache 主下载站在本机网络中实测只有约 14 KiB/s，因此归档改由阿里云 Apache 镜像下载；校验文件仍来自 Apache 官方下载站。归档 SHA-512：

```text
e25be7e57b4d3c5bfe83895844321a21d6cf7331266d524d8983c27cf484e576c3d79b3b60d590f8cddecf16229d0e232de2491b1b61b362ee7d67072c7290e1
```

本地计算值与 Apache 官方 `.sha512` 完全一致后才解压。`hadoop version` 与 `hdfs version` 均实际返回 `Hadoop 3.4.3`。

## 4. HDFS 关键配置

`core-site.xml`：

```xml
<property>
  <name>fs.defaultFS</name>
  <value>hdfs://127.0.0.1:9000</value>
</property>
```

`hdfs-site.xml`：

```xml
<property>
  <name>dfs.replication</name>
  <value>1</value>
</property>
<property>
  <name>dfs.namenode.name.dir</name>
  <value>file://${user.home}/hadoop_data/namenode</value>
</property>
<property>
  <name>dfs.datanode.data.dir</name>
  <value>file://${user.home}/hadoop_data/datanode</value>
</property>
<property>
  <name>dfs.namenode.rpc-address</name>
  <value>127.0.0.1:9000</value>
</property>
<property>
  <name>dfs.namenode.http-address</name>
  <value>0.0.0.0:9870</value>
</property>
<property>
  <name>dfs.datanode.http.address</name>
  <value>0.0.0.0:9864</value>
</property>
<property>
  <name>dfs.datanode.hostname</name>
  <value>127.0.0.1</value>
</property>
<property>
  <name>dfs.webhdfs.enabled</name>
  <value>true</value>
</property>
```

## 5. 首次格式化安全记录

格式化前执行了两轮检查：

- 未发现旧 Hadoop 安装或旧 HDFS NameNode 元数据；
- 当前 WSL 用户目录下的 NameNode 与 DataNode 数据目录在首次格式化前均为空；
- 未发现 `current/VERSION`；
- `jps` 仅显示检查命令自身；
- 9000、9870 未被占用。

第一次格式化调用因命令继承了包含中文的 Windows 挂载工作目录，Java 报 `InvalidPathException`，且确认未写入任何元数据。将工作目录固定为 WSL 用户主目录后首次格式化成功，没有删除或重新格式化旧数据。

生成的集群信息：

```text
clusterID=CID-040843fb-25e0-40af-bac6-f0a519bcb4aa
namespaceID=603715690
blockpoolID=BP-457327601-127.0.1.1-1786292941509
```

## 6. NameNode、DataNode 与端口状态

HDFS 采用两个用户级 systemd 服务：

- `hdfs-namenode.service`
- `hdfs-datanode.service`

实际 `jps` 验证包含：

```text
NameNode
DataNode
```

`hdfs dfsadmin -report` 实际结果包含：

```text
Live datanodes (1)
Name: 127.0.0.1:9866 (localhost)
Decommission Status : Normal
```

WSL 内实际监听：

| 端口 | 用途 | 结果 |
| --- | --- | --- |
| 9000 | NameNode RPC | `127.0.0.1:9000` 已监听 |
| 9870 | NameNode Web UI / WebHDFS | `0.0.0.0:9870` 已监听 |
| 9864 | DataNode HTTP | `0.0.0.0:9864` 已监听 |
| 9866 | DataNode 数据传输 | `0.0.0.0:9866` 已监听 |

Windows 侧 `netstat` 也能看到 127.0.0.1 的 9000、9870、9864、9866 监听。

## 7. WebHDFS 与课程目录验证

Windows PowerShell 实际调用：

```powershell
curl.exe "http://127.0.0.1:9870/webhdfs/v1/?op=GETHOMEDIRECTORY&user.name=hadoop"
```

真实返回：

```json
{"Path":"/user/hadoop"}
```

已建立并验证：

```text
drwxrwxr-x   - hadoop supergroup ... /bigdata_course
drwxrwxr-x   - hadoop supergroup ... /bigdata_course/bilibili
```

没有手工创建日期 `videos.jsonl`，日期目录与文件由项目 Python 后台自动创建。

## 8. Python HDFS 客户端验证

项目解释器：Python 3.11.9

使用项目真实 `services/hdfs_service.py` 完成：

1. WebHDFS 连接；
2. 临时日期目录与 JSONL 写入；
3. `save_to_hdfs()` 返回 `1`；
4. `read_from_hdfs()` 读回同一条 11 字段记录；
5. 删除临时测试日期目录。

实际输出：

```text
PROJECT_HDFS_OK saved=1 read=1 path=/bigdata_course/bilibili/date=2099-12-31/videos.jsonl
PROJECT_HDFS_CLEANUP path=/bigdata_course/bilibili/date=2099-12-31
```

测试数据已经清理，没有提交测试垃圾。

## 9. Task 4 真实联调结果

使用本地浏览器真实执行管理员页面操作：

```text
管理员登录
→ /collect
→ 输入“大数据技术”、2026-08-09、目标 1 条
→ 点击“开始采集”
→ POST /api/collect 返回 202
→ 页面显示 waiting/running
→ B站公开搜索与视频详情接口
→ pandas 清洗
→ WebHDFS 写入
→ MySQL 任务更新 success
→ GET /api/collect/status/5
→ 页面显示 success、成功数量 1 和最新真实视频
```

最终 MySQL 任务：

```text
task_id=5
status=success
success_count=1
finished_at=2026-08-10 00:43:59
message=采集完成
```

HDFS 真实文件：

```text
/bigdata_course/bilibili/date=2026-08-09/videos.jsonl
```

HDFS CLI 显示文件大小为 347 字节，内容为：

```json
{"bvid":"BV1y7421o7Na","title":"大数据技术入门精讲（Hadoop+Spark）","video_url":"https://www.bilibili.com/video/BV1y7421o7Na","up_name":"哈喽鹏程","publish_time":"2024-06-07 04:27:50","view_count":226444,"like_count":4133,"coin_count":2686,"favorite_count":13038,"share_count":1325,"collect_date":"2026-08-09"}
```

页面实际显示：播放 226444、点赞 4133、投币 2686、收藏 13038、分享 1325。数据结构只包含冻结的 11 个字段，不包含评论内容、`comment_count` 或 `stat.reply`。

联调期间还保留了一条失败证据：受限网络权限启动的 Flask 进程访问 B 站时返回 `[WinError 10013]`，任务 4 正确记为 `failed`；以允许公开网络访问的同一代码重启后，任务 5 完成上述真实链路，没有改用假数据或本地文件。

## 10. 日常启动与检查

由于当前未使用 Linux 管理员权限启用 user lingering，演示期间需要保持一个 Ubuntu/WSL 终端会话打开。在该终端执行：

```bash
systemctl --user start hdfs-namenode.service hdfs-datanode.service
source ~/.bigdata_course_env
jps
hdfs dfsadmin -report
```

然后在 Windows 项目目录启动 Flask：

```powershell
python app.py
```

可访问地址：

- Flask：`http://127.0.0.1:5000`
- NameNode Web UI：`http://127.0.0.1:9870`

停止 HDFS：

```bash
systemctl --user stop hdfs-datanode.service hdfs-namenode.service
```

不要再次执行 `hdfs namenode -format`。

## 11. 验收清单

- [x] Java 真实安装并能运行
- [x] `JAVA_HOME` 真实正确
- [x] Hadoop 真实安装
- [x] `hadoop version` 正常
- [x] `hdfs version` 正常
- [x] NameNode 运行
- [x] DataNode 运行
- [x] 9000 监听
- [x] 9870 监听
- [x] Windows 可访问 WebHDFS
- [x] `hdfs dfsadmin -report` 有 1 个 Live DataNode
- [x] `/bigdata_course` 与 `/bigdata_course/bilibili` 正常
- [x] Python HDFS 客户端真实连接、写入、读取、删除
- [x] 项目 `save_to_hdfs()` 真实成功
- [x] 项目 `read_from_hdfs()` 真实成功
- [x] 管理员真实 B 站采集任务最终为 success
- [x] `success_count=1`
- [x] `videos.jsonl` 真实出现在 HDFS
- [x] 页面真实回显成功

## 12. 历史问题与边界（已由第 14 节更新）

1. 首次配置时当前 WSL 用户的 systemd `Linger=no`；最终状态已变为 `yes`，本条只保留为历史问题记录。
2. 本次只完成用户要求的 Java + Hadoop/HDFS 与 Task 4 硬门禁，没有继续 Task 5，也没有安装或联调 Spark。
3. WSL 启动时提示 Windows localhost 代理不能自动映射到 NAT。该问题只影响 WSL 访问部分外部下载站，不影响 Windows 访问 HDFS localhost，也不影响项目当前联调。

## 13. 官方资料

- Apache Hadoop 3.4.3 发布与校验说明：<https://hadoop.apache.org/releases>
- Apache Hadoop 单节点配置文档：<https://hadoop.apache.org/docs/r3.4.3/hadoop-project-dist/hadoop-common/SingleCluster.html>
- Microsoft Build of OpenJDK 下载：<https://learn.microsoft.com/java/openjdk/download>
- Microsoft Build of OpenJDK 安装说明：<https://learn.microsoft.com/java/openjdk/install>

## 14. 当前最终状态（2026-08-13）

本节保留前文历史配置与失败证据，同时记录后续已经完成的修复和最终现场检查：

- MySQL 8.0.41 可连接，`bigdata_course` 中 `users`、`collection_tasks` 两张必需表存在。
- Hadoop 3.4.3 的 `hdfs-namenode.service`、`hdfs-datanode.service` 均为 `active`；`hdfs dfsadmin -report` 显示 `Live datanodes (1)`，节点为 `127.0.0.1:9866`。
- WebHDFS `http://127.0.0.1:9870` 返回 `{"Path":"/user/dr.who"}`；`/bigdata_course/bilibili/date=2026-08-09` 存在，正式数据可由项目读取。
- 当前 WSL 用户的 user lingering 已由 `no` 调整为 `yes`；Windows 计划任务 `BigDataCourse-HDFS` 在当前用户登录时启动 WSL、NameNode 和 DataNode，并持续承载 WSL 会话，因此不再要求保持可见 Ubuntu 终端。
- Windows `JAVA_HOME` 指向 IntelliJ JBR 21.0.8，PySpark/Spark 3.5.1 可运行；`spark-submit --version` 已验证，真实 Spark→HDFS 分析返回四组结果，浏览器四张 ECharts 图表正常显示。
- B站本机网络访问已恢复，真实采集曾成功返回 1 条数据。最终轻量接口检查返回 HTTP 200；公开接口仍可能短时返回 HTTP 412，该状态按外部风控边界记录，不使用代理池、Cookie 池、验证码或其他绕过方式。
- 前文 `Linger=no`、必须保持终端、Spark 未安装/未联调和 WinError 10013 固定存在等内容均为历史阶段记录，不再代表当前最终环境。
