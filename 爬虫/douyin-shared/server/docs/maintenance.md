# 维护与交接

```text
run.py / run.sh          命令行与服务器环境入口
pyproject.toml / uv.lock 独立、锁定的 Python 3.12 依赖
douyin_server/
  cli.py                参数、离线自检、Cookie 导入与退出码
  support.py            输入、文件检查、原子报告、进程锁
  backend.py            F2 会话适配和原脚本加载边界
  workflow.py           有界任务池、统计与校验报告
  range_downloader.py   可选 Range 分段，原独立模块复用
vendor/                 原脚本快照、原依赖文件及来源 SHA256
scripts/                环境准备、浏览器报告转 URL 清单
tests/                  离线输入、任务结果、分段协议测试
examples/urls.txt       公开 URL 格式示例
auth/                   使用者自行配置，不分发会话
downloads/ reports/     运行时创建；部署包不带历史数据
```

环境范围：本项目与上级浏览器项目有不同锁文件；上级使用 Python 3.10+、httpx 0.28、Playwright，本项目锁定 F2 所需的 httpx 0.27.2。禁止混用两套 uv.lock。

原脚本两份 Python 文件与服务器来源一致，见 `vendor/SOURCE.json`。`vendor/pyproject.toml`、`vendor/uv.lock` 为原测试环境快照，不是本项目安装入口。新项目依赖以根目录文件为准。

兼容适配集中在 backend.py：会话字段注入发生在当前进程，固定兼容标记来自既有验证，并非长期稳定的平台 SDK 签名。原下载客户端保留了 `verify=False` 的历史行为以维持运行条件；该行为不属于加速措施。需要更改 TLS 或 API 参数时，在独立环境单独验证，不改 site-packages。

CLI 通过导入原脚本的 process_url 复用取作品与下载逻辑，不调用依赖 sys.argv 的历史诊断脚本。一个命令进程只使用一套 Cookie。平台接口或 F2 变动优先改 backend.py；下载策略改 workflow/range_downloader；新增输入来源先输出标准作品 ID 清单，避免把发现和下载耦合。上级浏览器插件注册继续按其原文档维护。

离线验证（在本项目目录，使用已配置环境）：

```bash
bash run.sh doctor --no-cookie
./server/.venv/bin/python -m unittest discover -s tests -v
bash -n run.sh scripts/setup.sh
```

测试使用本地合成数据和 HTTP MockTransport，不调用抖音。一次测试通过不保证站点接口当前可用；正式部署后由使用者用一条目标作品做单独联网验收。

本次交接不修改远程原目录、依赖或共用服务，也不自动清理旧实验文件。上级根项目的 `scripts/build_server_bundle.py` 通过交付文件白名单生成 tar.gz，打包时排除登录态、缓存、视频、HAR、日志和报告。发布前复核文件清单与 SHA256。
