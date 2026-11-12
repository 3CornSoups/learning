# 本地采集、服务器下载

本地继续使用已登录的专用 Edge。`--export-manifest` 仅导出解析后的媒体任务，不下载本地视频，也不将任务写入本地“已完成下载”历史。Cookie、浏览器配置和原始抓包不进入任务清单。

```powershell
.\.venv\Scripts\python.exe .\crawl.py --source feed --limit 3 --export-manifest .\runs\jobs\batch.json
```

博主、标签和关键词模式也可使用此参数。输出文件必须是新文件，避免覆盖已有任务。任务清单内有临时媒体签名地址，应仅通过 SSH/SCP 传输，不提交仓库。

## 测试目录与环境

服务器项目根目录：`./douyin-current-snapshot`。

- `releases/版本/`：明确列入部署清单的代码、`pyproject.toml` 和 `uv.lock`。
- `tasks/`：媒体任务清单。
- `downloads/批次/`：视频和校验结果。
- `reports/`：探测、下载、重复执行和进程审计结果。
- `.cache/`：临时文件和缓存。

运行解释器为已有 `shared system environment/bin/python`。本次检查确认已有 `httpx==0.28.1`、OpenCV `4.10.0` 和系统 `ffprobe`，无需安装或同步依赖。服务器入口不导入 Playwright，不需要登录抖音，不使用 GPU。

依赖文件新增 `server` 依赖组，仅声明下载器所需的 httpx。以后确需同步时，先检查共用环境，显式指定 `/opt` 下目标环境，并保留额外依赖：

```bash
export UV_PROJECT_ENVIRONMENT=shared system environment
export UV_CACHE_DIR=./douyin-current-snapshot/.cache/uv
# 仅在核对环境并确有需要时执行；本次测试没有执行此命令
uv sync --only-group server --inexact
```

不要在 `~/projects` 下建立虚拟环境；项目文件、任务、下载、报告和大缓存不要写入 `/root`、`/tmp` 或系统盘。

## 下载入口

在指定代码发布目录中设置项目临时目录，再运行：

```bash
export TMPDIR=./douyin-current-snapshot/.cache/tmp
export XDG_CACHE_HOME=./douyin-current-snapshot/.cache
export PYTHONDONTWRITEBYTECODE=1
export CUDA_VISIBLE_DEVICES=''

# 参数路径替换成实际任务、输出和报告文件
shared system environment/bin/python server_worker.py --manifest /path/to/batch.json --output-dir /path/to/downloads --report /path/to/probe.json --probe
shared system environment/bin/python server_worker.py --manifest /path/to/batch.json --output-dir /path/to/downloads --report /path/to/download.json --verify-frames
```

先对每条媒体请求最多 64 KB，确认 HTTP 206、Content-Range 和 MP4 文件头。完整下载复用已有下载器的分段、大小及 MD5 校验，然后检查音视频轨道。`--verify-frames` 使用已有 OpenCV 抽查开始、中间和结尾，不会检查每一帧或解码音频。

再次执行相同任务时，已有文件必须重新通过大小、MD5 和轨道检查才会标记 `skipped_verified`，不会重复下载。损坏的已有文件不会被自动覆盖。下载和重放使用不同 `--report` 路径，以保留两次证据。

返回码：0 为全部任务完成；1 为下载、文件或清单错误；3 为 HTTP 401/403/410，需要本地刷新地址或排查网络。失败后保留未完成文件，报告中其余任务保持 `pending`，不会算作已完成。

## 人工验证与地址过期

搜索、主页和推荐页的验证码仍在本机由使用者处理，服务器不接收登录凭据。如果新导出的地址在服务器也返回 403，需要先比较本机和服务器访问结果、确认是否有出口限制；程序不会擅自切换其他采集方式。过期地址通过本地重新解析生成新任务文件，当前不包含自动调度、自动回传刷新或无人值守验证码处理。

每次远程运行结束后，应核对报告中的 PID、后台任务、子进程及 GPU 占用；只清理确认属于本任务的残留。部署不会改动原 `~/projects/Video_group/Crawler` 中的脚本。


## 2026-11-10 实测结果

代码发布目录为 `./douyin-current-snapshot/releases/migration-20261110a`，视频位于 `./douyin-current-snapshot/downloads/batch01`，验收报告为服务器 `reports/migration_acceptance.json`，本地副本在 `runs/server-migration/results/migration_acceptance.json`。

本机从推荐流发现并导出 3 条新任务，没有在本机下载这 3 个视频。服务器先逐条探测成功，再下载总计 14,589,640 字节。3 份文件均通过大小、MD5、音视频轨道、开头/中间/结尾抽帧解码，以及独立 ffprobe 检查。重复运行同一任务，3 份文件全部 `skipped_verified`。服务器 3 项离线传输测试、本机 14 项测试通过。

本次没有安装或同步服务器依赖。环境包版本清单的散列在测试前后一致，原 `./douyin-shared` 两份脚本的 SHA-256 未改变。报告记录的 3 个 worker PID 均已退出，没有相关残留进程、GPU 进程或分段文件。

以下为当前已部署版本的实际运行方式（地址过期后应先从本机导出新的任务，不应盲目反复重试旧地址）：

```bash
cd ./douyin-current-snapshot/releases/migration-20261110a
export TMPDIR=./douyin-current-snapshot/.cache/tmp
export XDG_CACHE_HOME=./douyin-current-snapshot/.cache
export PYTHONDONTWRITEBYTECODE=1
export CUDA_VISIBLE_DEVICES=''
export OPENCV_OPENCL_RUNTIME=disabled
shared system environment/bin/python -B server_worker.py \
  --manifest ./douyin-current-snapshot/tasks/batch01.json \
  --output-dir ./douyin-current-snapshot/downloads/batch01 \
  --report ./douyin-current-snapshot/reports/batch01.manual-replay.json \
  --verify-frames
```
