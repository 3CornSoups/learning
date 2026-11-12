# 抖音视频采集项目

**服务器使用先看 [server/README.md](server/README.md)**。`server/` 已整理为可以独立放到 `~/projects` 下的项目，包含运行入口、独立依赖锁、Cookie 配置、输入示例、自检、失败报告和排障说明。

## 选择入口

| 使用目标 | 入口 / 文档 |
|---|---|
| 服务器接收作品 URL 批量下载；本机可以离线 | `server/run.py`，见 [服务器快速上手](server/README.md) |
| 本机自动获取推荐流、某博主作品、标签或关键词视频 | 根 `crawl.py`，见 [本机浏览器使用说明](docs/local-browser.md) |
| 按 UID、标签或关键词发现，再交给服务器下载 | 本机 `crawl.py --discover-only`，再用 `server/scripts/jobs_to_urls.py` 转为 URL 清单 |
| 查看原验证结果及速度、波动 | [历史优化记录](F2_DOWNLOAD_OPTIMIZATION.md)、[交付包性能摘要](server/docs/performance.md) |
| 查看旧脚本、历史实验与私有数据位置 | [目录用途与整理说明](docs/project-layout.md) |

服务器 F2 入口和本机浏览器项目使用**两套独立依赖**。根 `pyproject.toml / uv.lock` 属于浏览器项目；服务器安装使用 `server/pyproject.toml / server/uv.lock`，独立环境默认 `./server/.venv`。不要将两者混装到共用 `shared system environment`。

## 服务器交付

本机现成发布包：`dist/douyin-server-0.2.0.tar.gz`。仅包含交付白名单文件，附 SHA256 和文件清单；不包含 Cookie、浏览器登录态、视频、HAR、个人环境或历史运行报告。

1. 将发布包放到本人 `~/projects` 项目位置并解压，进入解压后的 `douyin/`。
2. 按 [服务器 README](server/README.md) 检查独立环境，导入自己的 Cookie。
3. 先执行输入清单 `--dry-run`，再用一条作品验收，成功后扩大批次。

本次整理未部署或覆盖服务器目录，也未再运行真实采集。服务器交付包装新增自检与校验，离线检查不能替代目标平台当前可用性验证。历史测速数据仍对应之前已实采的入口。

## 本机功能

已有本机项目及数据保留原位置，避免破坏浏览器配置、虚拟环境和去重记录。使用 Windows 专用 Edge 手动登录；验证码需人工处理。推荐流、博主全量、标签、关键词和标题筛选、插件扩展仍按 [本机文档](docs/local-browser.md) 使用。

根目录 `download_douyin.py / download_by_urls.py` 是最初的研读副本；`SERVER_MIGRATION.md` 等属于旧实验记录。正式服务器交接请使用 `server/`，不要直接从旧实验缓存复制脚本运行。

## 维护检查

```powershell
# 本机已有浏览器环境可以运行服务器包装的离线单元测试，无需登录或实采
cd server
..\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd ..
# 重新生成仅含交付文件的发布包
.\.venv\Scripts\python.exe scripts/build_server_bundle.py
```

服务器上的同等检查、环境重建和扩展边界见 [维护说明](server/docs/maintenance.md)。
