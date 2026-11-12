# 项目整理说明

本次整理新增独立 `server/` 交付单元，根项目保留本机浏览器功能与已有运行数据，避免移动虚拟环境、浏览器配置或历史记录后破坏可运行状态。

| 区域 | 内容 | 是否上传服务器 |
|---|---|---|
| `server/` | 独立服务器代码、依赖锁、配置说明、测试 | 推荐仅上传由它构建的发布包 |
| 根 `crawl.py`、`douyin_crawler/`、`plugins/`、`examples/` | 已有本机 Edge 自动发现与筛选 | 需要本机发现能力时保留在 Windows |
| 根 `pyproject.toml`、`uv.lock` | 本机浏览器环境 | 不用于服务器 F2 安装 |
| 根 `download_douyin.py`、`download_by_urls.py` | 最初用于本地研读的带注释副本 | 不作为正式服务器入口 |
| `server_session.py`、`server_worker.py`、`export_auth.py`、`start_server_browser.sh` | 早期浏览器迁移/媒体任务传输实验入口 | 当前主交付不需要 |
| `docs/local-browser.md` | 原本机功能说明，命令在根项目执行 | 阅读用 |
| `F2_DOWNLOAD_OPTIMIZATION.md`、`F2_ORIGINAL_VALIDATION.md` | 历史验证和优化记录 | 保留，不替代新交付文档 |
| `SERVER_MIGRATION.md`、`SERVER_BROWSER_TEST.md`、`本地验证说明.md` | 旧阶段实验文档 | 仅历史参考 |
| `runs/`、`verified_downloads/`、`downloads/` | 历史报告和媒体数据 | 不进发布包 |
| `auth/`、`browser_profile/`、`test_page.html`、`*.har` | 登录态及可能包含会话的诊断文件 | 私有，不分发 |
| `.cache/`、`.tooling/`、`.venv/`、`pip-*` | 个人环境、临时文件、实验代码与会话 | 不分发，不因整理而强制删除 |

历史文件没有批量搬迁或删除，根环境和已有浏览器配置保持原位置。旧文件在这里明确标注用途，新使用者按根 README → server/README 的路径上手，避免从旧诊断脚本入手。

发布命令在本机根项目执行，只有标准库需求，不会抓取：

```powershell
.\.venv\Scripts\python.exe scripts/build_server_bundle.py
```

产物为 `dist/douyin-server-0.2.0.tar.gz`、同名 `.sha256` 和 `.manifest.json`。tar 内顶层为 `douyin/`，其内容与 `server/` 交付文件一致。文件白名单明确写在打包脚本中，新加交付模块时同步更新白名单。真实 Cookie、账号文件、视频和个人环境不会因为放进 server 子目录而自动被打包。
