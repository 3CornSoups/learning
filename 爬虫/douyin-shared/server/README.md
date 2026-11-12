# 抖音服务器下载项目

本目录是可独立复制的交付单元。把本目录的**内容**放到服务器项目目录即可运行，不依赖上级项目、实验缓存或本机浏览器。默认接收作品 URL 清单，5 文件并发、每文件单连接；正常下载时本机可以关机。

版本：0.2.0。复用已验证的原 F2 下载脚本和会话适配，增加配置检查、结果校验、输出锁及 JSON 报告。此次整理只做离线验收，未对新包装入口重新实采或测速。历史性能见 [测速记录](docs/performance.md)。

## 1. 放到哪里

| 内容 | 路径 / 要求 |
|---|---|
| 原共享脚本 | `./douyin-shared`，不要直接覆盖 |
| 既有验证目录 | `./original-f2-test`，保留作对照 |
| 本交付包建议部署位置 | `./douyin-current-snapshot-server/0.2.0/douyin` |
| 独立环境 | `./server/.venv`；Python 3.12、F2 0.0.1.7、httpx 0.27.2 |
| 共用环境 | `shared system environment`，不对它同步本项目依赖 |
| 视频 / 报告 / Cookie | 本项目 `downloads/`、`reports/`、`auth/cookie.txt` |
| 缓存 / 临时文件 | 本项目 `.cache/`，由启动脚本设置 |

部署路径可以变，但 Linux 运行目录及写入路径必须位于 `~/projects`。环境位于 `/opt`。原共享环境的 httpx 版本与本项目不同，因此使用已有独立环境；不要把本项目锁文件同步到 `shared system environment`。

## 2. 首次启动

先上传并解压发布包，进入解压出的 `douyin/`。不要把本机整个工程（含 `.venv`、Cookie、浏览器配置和视频）原样上传。以下命令在**服务器 Bash**执行。

```bash
cd ./douyin-current-snapshot-server/0.2.0/douyin

# 先检查已有独立环境；不联网，不采集，不安装依赖
bash run.sh doctor --no-cookie
```

若已有环境检查通过，直接进入 Cookie 配置。环境不存在或依赖不符时，确认项目路径后运行：

```bash
# 需要服务器已有 uv 和 Python 3.12；仅同步独立环境
export UV_PROJECT_ENVIRONMENT=./server/.venv
bash scripts/setup.sh
```

`setup.sh` 会显示项目、环境和缓存位置，使用锁文件同步，拒绝 `shared system environment`。如果独立环境也被其他任务使用，请另选一个 `/opt` 环境，不要在任务运行中同步。新建环境不修改 `shared system environment`，但使用它的 Python 作为解释器来源时，该 Python 仍需保留。

## 3. 配置 Cookie

按 [Cookie 获取说明](docs/cookie.md) 从已登录浏览器获取**完整单行请求头值**，通过 SSH/SCP 或远程编辑器保存在 `~/projects` 的本人私有文件中。不要放在命令行里或发到聊天。

```bash
# 将下面的路径替换为实际私有文件路径
bash run.sh import-cookie --from-file ~/projects/本人目录/fresh_cookie.txt
# 以后刷新同一配置时加 --replace
bash run.sh cookie-check
bash run.sh doctor
```

也可直接私密上传为 `auth/cookie.txt`，执行 `chmod 600 auth/cookie.txt`。离线检查通过只表示格式和环境正确，不保证会话仍有效。Cookie 不随交付包分发。

## 4. 准备链接并下载

复制 `examples/urls.txt` 为自己的输入文件，每行一个完整作品 URL 或数字作品 ID，支持 `#` 注释，重复 ID 自动合并。支持 `/video/ID`、`/note/ID` 及含 `modal_id=ID` 的网页 URL；短链接需要先在浏览器展开。图集不计为成功视频。

```bash
# 只解析输入，完全不请求抖音，不需要 Cookie
bash run.sh download -i examples/urls.txt --limit 5 --dry-run

# 首次先下 1 条，确认成功后再扩大批次
bash run.sh download -i examples/urls.txt --limit 1 -o downloads/smoke_001

# 5 文件并发，默认不分段；有 ffprobe 时可增加媒体轨道检查
bash run.sh download -i urls.txt -o downloads/batch_001 -c 5 --verify ffprobe

# 可选分段实验，单文件默认上限 100 MB；不保证比默认方案快
bash run.sh download -i urls.txt -o downloads/range_001 -c 5 --segments 2
```

所有入口的相对路径以**本服务器项目目录**为基准，与执行命令时所在目录无关。`--from-file`、`--cookie-file` 同样遵守此规则。脚本可在不同工作目录调用。

| 常用参数 | 默认值 / 含义 |
|---|---|
| `-i / --input-file` | 必填，UTF-8 清单 |
| `-o / --output-dir` | `downloads`，建议每个业务批次独立子目录 |
| `--cookie-file` | `auth/cookie.txt` |
| `-c / --concurrency` | 5，允许 1–16；只实测过 4 与 5 |
| `--limit` | 不设则处理清单全部唯一 ID；设定时必须大于 0 |
| `--segments` | 1，可选 2 / 4；分段功能为可选实验 |
| `--range-connections` | 12，限制所有文件的活跃分段请求总数 |
| `--verify` | `basic`；`ffprobe` 额外检查视频轨道，需要 ffprobe |
| `--report` | 默认自动生成唯一的 `reports/UTC时间-PID.json` |
| `--dry-run` | 仅解析输入，不产生下载或报告文件 |

## 5. 成功判定、续跑与排障

每轮报告给出 downloaded、skipped、failed、pending_ids、耗时、实际新增字节及整批 MB/s。`state=complete` 仅表示任务遍历结束，成功还要核对 failed=0、pending_ids 为空和退出码。

| 退出码 | 含义 |
|---|---|
| 0 | 所有作品下载或校验后跳过；离线命令则表示该项检查通过 |
| 1 | 存在下载失败、未完成任务或后端异常 |
| 2 | 配置、依赖、输入或本地文件错误 |
| 130 | 人工中断 |

成功文件命名为 `作品ID_作者_文案.mp4`，索引为输出目录 `.douyin-index.json`。重复运行同一输入与输出会跳过已存在文件，仍检查 MP4 文件头、MD5 和已有索引。接口提供媒体散列时检查匹配；`source_hash_verified=null` 表示没有本次源散列，**不是完整性已经被源端证明**。首次遇到没有旧索引和源散列的文件，basic 只能检查容器头并记录当前 MD5；需要更强检查时使用 ffprobe。ffprobe 也不等于完整逐帧解码。

失败或中断后可用相同命令重试，成功文件不会重复下载。原脚本遗留的 `.tmp` 文件不支持跨进程断点续传。损坏的既有 MP4 会报告失败，不自动覆盖，请先保留现场再用新输出目录。不要同时向同一输出目录运行两个进程，操作系统锁会拒绝第二个任务。

遇到登录/验证码/403，先停止批量任务，回本机手动验证并更新 Cookie，不要无限重试。详细现象对应见 [运行与排障](docs/operations.md)。

## 6. 按博主 UID、标签、关键词发现视频

本服务器交付入口的正式输入是 URL 清单，**不宣称已经实现服务器独立推荐流、关键词搜索或全量博主发现**。这些功能继续使用上级本地浏览器项目，见根项目 `docs/local-browser.md`。抖音博主标识使用主页里的 `sec_user_id`（`MS4...`），不是昵称或抖音号。

在本机根项目中执行：

```powershell
.\.venv\Scripts\python.exe crawl.py --source author --author "博主主页URL或MS4..." --all --discover-only
# 也可 --source hashtag --tag "摄影" 或 --source search --keyword "教程" --title-contains "教程"
```

找到打印出的本轮 `report.json`，在本机转成服务器清单：

```powershell
.\.venv\Scripts\python.exe server/scripts/jobs_to_urls.py runs/本轮目录/report.json urls.txt
```

该转换也接受本地 `--export-manifest` 产出的清单，只提取作品 ID，不复制媒体临时地址或 Cookie。将生成的 `urls.txt` 上传服务器，再运行第 4 节命令。本机完成发现和上传后可以关机。全量仅指账号当前可见、分页确认结束的公开视频，不包含私密、删除或不可见作品。

## 7. 维护与扩展

目录职责、适配边界和离线测试见 [维护说明](docs/maintenance.md)。`vendor/` 两个原脚本按 SHA256 保持原样；新功能改在 `douyin_server/`，不要修改环境中的第三方包。修改依赖用 uv 同步更新 `pyproject.toml` 与 `uv.lock`，先在独立环境验证。

几十万条任务尚未长期验收。先按几百条拆分任务清单，观察失败率、账号状态和磁盘容量；5 并发是已测试配置，不是站点或服务器的并发极限。不要据短批次速度直接推算长期每日产量。
