# 原始 F2 脚本的隔离验证

2026-11-10 已实测：F2 纯 HTTP 路线能够在服务器下载视频，不需要本机浏览器持续在线。但当前原脚本原样加 Cookie 会返回 403，需要补充当前接口的兼容字段。

## 测试位置

- 原目录：`./douyin-shared`，没有修改。
- 副本与项目依赖：`./original-f2-test`。
- 独立环境：`./server/.venv`，使用 F2 `0.0.1.7`、httpx `0.27.2`。
- `pyproject.toml` 与 `uv.lock` 在测试目录；依赖通过 `uv add` 配置，共用 `shared system environment` 没有安装或同步依赖。
- `cookie.txt` 来自本机已存在的抖音登录态，经 SSH 传输，未打印凭据值。

两份脚本的原件和副本 SHA-256 均相同：

```text
download_douyin.py   fa3b5af178ea28a48914d4f1b095d2c63de8847891905423cabec1ea4ca1d92c
download_by_urls.py  5ec5d94a58a4102424ade7e7d8757428cfbcf19a093acf1b87b3ab803cd65b6a
```

## 原样与兼容对照

| 方式 | 作品详情接口 | 博主作品接口 | 实际视频 |
|---|---|---|---|
| 原样脚本 + 有效 Cookie + PyPI F2 | 403 | 403 | 0 条 |
| 同一脚本 + 外置兼容适配器 | 200 | 200 | 两个入口各 1 条 |

原样请求里的 Cookie 与文件完全一致。服务端固定错误为 `Blocked by ArgusSecurityPlugin Uifid Not Found`，所以不是 Cookie 文件位置错误。F2 官方问题区有同类报告：<https://github.com/Johnserf-Seed/f2/issues/443>。

`bounded_probe.py --compat` 仅在当前 Python 进程内适配 F2：从同一 Cookie 提取 `UIFID`/`UIFID_TEMP`、`s_v_web_id`，补充 `uifid` 请求头和 `uifid`、`verifyFp`、`fp` 参数，并参考现有实现设置 `x-tt-argus`。所有参数在 F2 生成请求签名前进入模型，不直接修改已签名的地址。没有修改 site-packages 或两份脚本正文。

其中 `x-tt-argus` 的固定值是当前兼容方法，并非长期有效的真实 SDK 签名；如果平台升级校验，仍可能失效。本次两条成功不能证明大批量或长期稳定性。

## 小批量结果

- 链接入口：1 条，842,273 字节，约 5.07 秒。
- 博主入口：最多读取一页，并只交给原脚本下载一条小于 30 秒、20 MB 的普通视频；实下 1 条，2,029,652 字节，约 7.15 秒。
- 两条视频都通过 ffprobe 音视频轨道检查，以及开头、中间、结尾抽帧解码。
- 报告记录实际文件 MD5；本次未将它与接口预期 MD5 做对比，不将其描述为源文件散列匹配。
- 原目录、副本、共用环境包版本清单均保持不变；记录的测试 PID 已退出。

输出：`output/urls_audited/`、`output/author_one/`。
报告：`reports/f2_acceptance.json`，以及原样/兼容两组 `*.audit.json`。

原脚本在失败时可能仍打印 `Download completed!`、返回退出码 0，必须检查成功计数和真实文件，不能只看退出码。

## 复现命令

```bash
cd ./original-f2-test
export HOME=$PWD/.cache/home
export TMPDIR=$PWD/.cache/tmp
export XDG_CACHE_HOME=$PWD/.cache
export PYTHONDONTWRITEBYTECODE=1
export CUDA_VISIBLE_DEVICES=''

# urls.one.txt 每行一个作品链接；test_author.txt 为公开博主 sec_user_id
./server/.venv/bin/python -B bounded_probe.py urls --compat
./server/.venv/bin/python -B bounded_probe.py author --compat
```

这是限量验证器，不是完整批量任务调度器。它只限制博主返回给原脚本的数据，不改变原接口调用、签名和下载逻辑。链接模式保留原脚本的跳过已有文件行为；博主原脚本可能覆盖同名输出，重复验证前应另行准备输出位置。

需要重建环境时，先核对路径：

```bash
export UV_PROJECT_ENVIRONMENT=./server/.venv
export UV_CACHE_DIR=$PWD/.cache/uv
uv sync --frozen
```

不要直接对共用环境执行该项目的同步：F2 固定了与共用环境不同的 httpx、pydantic、cryptography 等版本。

Cookie、原始错误日志和缓存均只保存在私有测试目录，不应分享或提交仓库。此前暂停的服务器浏览器/远程桌面测试未被本次恢复或修改。
