说明：本页保留本机浏览器项目的完整用法。以下命令均在根项目 douyin/ 执行；服务器交付改看 [server/README.md](../server/README.md)。

# 抖音视频采集器

服务器原 F2 脚本的独立验证、下载加速参数与同一组 5 条视频测速结果，见 [下载优化与运行说明](../F2_DOWNLOAD_OPTIMIZATION.md)。该路线不需要本机浏览器持续在线；当前默认使用 5 文件并发，分段下载为可选实验功能。

使用本机已登录的专用 Edge 自动发现公开视频，支持推荐流、博主主页、关键词搜索、精确标签，以及标题/文案筛选。统一入口为 `crawl.py`；原 `crawl_feed.py` 是兼容入口，接受同样的参数。

“新视频”指当前历史记录中尚未下载过的作品，不保证是刚发布的作品。推荐、搜索排序和可访问内容由抖音决定。

## 1. 安装与登录

需要 Windows、Python 3.10 或以上、已安装的 Microsoft Edge。当前本机的 `.venv` 已配置好，可以直接使用下一节的命令。

其他人首次使用时，在项目目录执行：

```powershell
python -m venv .tooling
.\.tooling\Scripts\python.exe -m pip install uv
$env:UV_PROJECT_ENVIRONMENT = Join-Path $PWD '.venv'
$env:UV_CACHE_DIR = Join-Path $PWD '.cache/uv'
.\.tooling\Scripts\uv.exe sync --frozen
```

无需另行安装 Chromium。依赖声明和锁文件分别为 `pyproject.toml`、`uv.lock`。

```powershell
# 打开专用 Edge，手动登录小号，保存登录态后退出
.\.venv\Scripts\python.exe .\crawl.py --login-only
```

普通采集命令也会检测登录状态，首次使用或登录失效时最多等待 600 秒，供你手动登录。登录跳转后继续检测，不要求手动复制 Cookie。登录态保存在 `browser_profile/`，可使用 `--profile-dir` 指定其他目录。不要同时用两个进程打开同一个浏览器配置目录。

验证码和安全验证由使用者手动完成。检测到验证页后，程序打印 `HUMAN_VERIFICATION_REQUIRED` 并等待，不会自动解题或更换采集方式。使用 `--login-timeout 1800` 可将等待时间增加至 30 分钟；超时会报错退出并保留报告。

程序只为自身进程设置项目临时目录 `.cache/tmp/`，不更改系统临时目录设置。

## 2. 常用命令

以下命令都在项目目录中执行。

### 自动获取推荐视频

```powershell
# 不提供视频链接，默认下载 3 条
.\.venv\Scripts\python.exe .\crawl.py

# 下载 10 条
.\.venv\Scripts\python.exe .\crawl.py --source feed --limit 10
```

### 下载某博主的全部公开视频

将 `博主主页URL` 替换为从网页地址栏复制的完整主页，例如 `https://www.douyin.com/user/MS4...`；也可直接传 `MS4...` 形式的 sec_user_id。不接受昵称、抖音号、视频分享链接或 `v.douyin.com` 短链接。

```powershell
# 全量模式：遍历该博主当前可访问的作品页，下载其中的公开视频
.\.venv\Scripts\python.exe .\crawl.py --source author --author "博主主页URL" --all

# 先小批测试，最多下载 5 条符合条件、尚未下载过的视频
.\.venv\Scripts\python.exe .\crawl.py --source author --author "博主主页URL" --limit 5

# 先只发现、筛选，不下载文件
.\.venv\Scripts\python.exe .\crawl.py --source author --author "博主主页URL" --all --discover-only
```

`--all` 会取消默认的 3 条数量、180 秒时长、100 MB 单文件限制，默认最多滚动 1000 次。只有作品接口明确返回 `has_more=0`，且已处理完该次运行捕获的最后一页，才报告遍历完成。达到滚动上限、接口报错、分页游标不前进或验证超时，都不会被报告为“全部完成”。

“全部”仅指当前登录账号能访问到、该次遍历返回的公开视频，排除图集、广告、私密和已删除作品。已经完整下载的文件会跳过。新增的标题或标签条件仍然生效，因此添加条件后代表“全部符合条件的视频”。不会冻结博主在采集期间的发帖状态。

若同时显式设置 `--max-duration` 或 `--max-video-mb`，这些限制仍然生效。无法保证在平台动态加载、内容更新或限制访问的情况下枚举历史上所有作品；报告会明确区分范围和停止原因。

### 搜索某关键词

```powershell
.\.venv\Scripts\python.exe .\crawl.py --source search --keyword "机器学习" --limit 10
```

搜索结果可能是平台判定的相关内容，并不保证标题中含该词。需要严格的文字条件时叠加下一项筛选。

### 标题或作品文案包含某个词

```powershell
# 搜索“机器学习”，只下载标题/文案确实包含该词的结果
.\.venv\Scripts\python.exe .\crawl.py --source search --keyword "机器学习" --title-contains "机器学习" --limit 10

# 多次传入表示所有词都必须出现；不区分英文字母大小写
.\.venv\Scripts\python.exe .\crawl.py --source search --keyword "人工智能" --title-contains "AI" --title-contains "教程" --limit 5

# 同样可用于博主作品
.\.venv\Scripts\python.exe .\crawl.py --source author --author "博主主页URL" --title-contains "教程" --all
```

文字匹配范围为 `item_title/itemTitle` 标题与 `desc/caption` 作品文案，不包含评论、语音转写或视频字幕。重复 `--title-contains` 默认是 AND，字面子串匹配；OR 和正则表达式可用 JSON 配置。

### 精确标签

```powershell
# 自动搜索标签，再按作品实际 hashtag 元数据精确筛选
.\.venv\Scripts\python.exe .\crawl.py --source hashtag --tag "猫咪" --limit 10

# 给其他来源叠加标签条件
.\.venv\Scripts\python.exe .\crawl.py --source author --author "博主主页URL" --tag "摄影" --all
```

`--tag "猫咪"` 与 `--tag "#猫咪"` 等价。结构化 hashtag 元数据优先，缺失时解析文案中的 `#标签`；“猫咪日常”不会被当作“猫咪”精确匹配。标签模式使用平台搜索发现候选，再严格过滤，并不承诺枚举平台上所有带此标签的视频。

## 3. 参数与默认值

| 参数 | 作用 |
|---|---|
| `--source` | `feed`、`author`、`search`、`hashtag` 或注册的自定义来源；默认 `feed` |
| `--author` | 博主标准主页 URL 或 sec_user_id，仅用于 `author` |
| `--keyword` | 搜索词，仅用于 `search` |
| `--tag` | 精确 hashtag；`hashtag` 来源必填，也可用于其他来源 |
| `--title-contains` | 标题/文案包含词，可重复传入，默认全部满足 |
| `--limit` | 本次最多新增下载或选择的数量；默认 3，不与 `--all` 同用 |
| `--all` | 博主全部符合条件的公开视频；数量不限，默认取消时长和大小限制 |
| `--max-scrolls` | 普通模式默认 20；全量模式默认 1000；0 表示仅处理首批加载的数据 |
| `--max-duration` | 最大时长，单位秒；普通模式默认 180，0 表示不限 |
| `--max-video-mb` | 单文件最大大小，单位十进制 MB；普通模式默认 100，0 表示不限 |
| `--wait-seconds` | 每次滚动后等待数据的秒数，默认 4，最小 1 |
| `--discover-only` | 只发现、筛选并记录 `selected`，不下载、不写入完成历史 |
| `-o / --output-dir` | 视频输出位置，默认项目下 `downloads/` |
| `--profile-dir` | 专用 Edge 登录态位置，默认项目下 `browser_profile/` |
| `--state-dir` | 历史数据库与报告位置，默认项目下 `runs/` |
| `--login-timeout` | 登录或人工验证最长等待秒数，默认 600 |
| `--config` | JSON 任务文件；命令行提供的值覆盖配置文件 |
| `--export-manifest` | 导出已解析的媒体任务清单，不在本地下载，不与仅发现/登录/诊断模式混用 |
| `--plugin` | 加载自定义扩展模块，可重复传入 |
| `--inspect` | 保存当前来源页面的 HTML/正文供本地诊断，不执行下载 |

所有来源与筛选条件组合使用时采用 AND。普通批次如果先遇到接口明确的结果末尾，即便数量不足也会结束，并在报告中写明 `source_exhausted`；未确认末尾而达到滚动上限时返回未完成。

## 4. JSON 任务文件

```powershell
.\.venv\Scripts\python.exe .\crawl.py --config .\examples\search.json
.\.venv\Scripts\python.exe .\crawl.py --config .\examples\hashtag.json --limit 1
.\.venv\Scripts\python.exe .\crawl.py --config .\examples\with_plugin.json
```

示例：搜索相关视频，要求标题/文案包含任一词，并匹配一个正则：

```json
{
  "source": "search",
  "keyword": "人工智能",
  "limit": 10,
  "rules": [
    {"type": "title_contains", "words": ["AI", "人工智能"], "match": "any"},
    {"type": "title_regex", "pattern": "教程|入门"}
  ],
  "output_dir": "./media"
}
```

配置文件使用 UTF-8 JSON；未知键会报错，避免拼写错误被忽略。配置中的相对路径以配置文件目录为基准；命令行相对路径以当前工作目录为基准。CLI 中的列表选项会替换对应配置列表，不是追加。`--limit` 可以将配置中的全量任务改为小批任务；CLI `--all` 可覆盖文件中的 `limit`，但同一命令不能同时写 `--all --limit`。

## 5. 输出、去重与完成状态

```text
crawl.py                    统一命令行入口
crawl_feed.py               兼容入口
pyproject.toml / uv.lock    可复现依赖
examples/                   JSON 任务样例
plugins/                    自定义来源/筛选扩展
douyin_crawler/
  config.py                 参数和配置文件
  models.py                 统一 Video 数据结构
  sources.py                页面导航、响应范围、分页终止
  filters.py                可组合筛选规则
  browser.py                登录等待、人工验证等待、播放入口解析
  history.py                完成记录及旧文件记录导入
  runtime.py                通用采集和下载流程
downloads/
  作品ID.mp4                完成文件
  作品ID.json               标题、标签、大小、MD5、来源等
runs/
  history.sqlite3           完成记录
  每轮时间/report.json      本轮配置、发现、筛选、下载、跳过、错误及覆盖范围
  每轮时间/candidates.json  浏览器实际返回的作品数据，供本地排查
```

完成记录按作品 ID 去重。跨推荐、搜索、标签和博主来源共享同一 `state-dir` 时，同一作品只下载一次；每次检查其完成文件是否仍存在、大小是否匹配。想隔离任务历史，可指定不同 `--state-dir` 和输出目录。

视频使用作品数据提供的播放入口解析地址，以分段请求下载；合并时检查字节范围、大小及接口可用的 MD5，并检查音视频轨道。网络或解析异常时停止，保留 `.part` 和对应分段。媒体地址仍有效且再次发现同一作品时，可复用未完成文件；当前不保存可恢复的推荐/搜索分页游标。

程序不会忽略错误后继续宣称全量完成。单次批量的目标是新增文件数，已下载和被过滤的作品不占 `--limit`。`--discover-only` 则以符合条件且未下载的 `selected` 数量作为目标。

| 返回码 | 含义 |
|---|---|
| 0 | 达到批次目标、收到来源末尾，或完成登录/诊断操作；须结合 `stop_reason` 理解 |
| 1 | 登录/验证超时、接口、解析或下载错误 |
| 2 | 配置错误，或达到滚动上限但未确认来源结束 |

报告中的 `completed`、`stop_reason`、`coverage` 和 `source_exhausted` 用于区分请求批次、完整来源遍历与未完成状态。`completed=true` 的小批次不代表博主所有视频已下载。浏览器下载期间自动预取的最后一页也会先处理完，才允许报告来源遍历结束。

## 6. 如何添加新功能

### 新增筛选规则：只加扩展文件，不改下载流程

项目提供可直接使用的 `plugins/min_likes.py`。规则工厂接收一个 JSON 对象，返回一个接受 `Video` 的函数；通过时返回 `None`，不通过时返回可记录的原因字符串。

```python
from douyin_crawler.filters import register_filter


def minimum_likes(options):
    threshold = int(options["value"])

    def rule(video):
        count = (video.raw.get("statistics") or {}).get("digg_count", 0)
        return None if count >= threshold else "min_likes"

    return rule


def register():
    register_filter("min_likes", minimum_likes)
```

启用方式见 `examples/with_plugin.json`：指定 `plugins` 模块列表和 `rules`，或使用 `--plugin plugins.min_likes` 加载模块。模块必须有无参 `register()`，通过 `register_filter` 注册；同名注册会报错。

`Video` 提供 `id`、`title`、`description`、`author_id`、`hashtags`、`duration_ms`、`size_bytes` 和原始 `raw`，常见新规则不必重新解析平台字段。

### 新增采集来源：实现来源模块，再注册

来源接口集中在 `douyin_crawler/sources.py`：

- `url`：初始页面。
- `matches(response_url)`：只接收属于当前任务的接口响应，防止把推荐或其他博主的视频混入。
- `read(response_url, payload)`：将响应转换为 `Video` 列表，并更新 `pages` 和 `exhausted`；接口错误或不前进的分页应报错。
- `advance(page)`：通过浏览器继续加载下一批数据。
- `supports_all`：只有能够可靠识别末页的来源才开启。

扩展通过 `register_source(name, factory)` 注册，工厂接收 `Config`，返回来源对象。`source_options` 是为自定义来源预留的 JSON 对象，不需要给每个新参数增加 CLI 选项。

例如把下列内容保存为 `plugins/custom_search.py`，即可复用现有搜索实现：

```python
from dataclasses import replace
from douyin_crawler.sources import SearchSource, register_source


def make_source(config):
    keyword = config.source_options.get("query", "猫咪")
    return SearchSource(replace(config, keyword=keyword))


def register():
    register_source("custom_search", make_source)
```

对应配置：

```json
{
  "source": "custom_search",
  "plugins": ["plugins.custom_search"],
  "source_options": {"query": "摄影教程"},
  "limit": 3
}
```

真正不同的网站入口或分页方式，可以继承 `Source` 实现上述接口；无需改动登录、历史记录或下载器。注册扩展会在本机执行该 Python 模块，因此只加载自己认可的项目代码。

## 7. 验证与范围

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 可选：安装 OpenCV 并抽查文件开头/中间/结尾画面
.\.tooling\Scripts\uv.exe sync --frozen --extra verify
.\.venv\Scripts\python.exe .\verify_media.py .\downloads\作品ID.mp4
```

2026-11-10：统一入口已实际验证推荐、博主主页、关键词搜索叠加标题筛选、精确标签四种下载路径。博主全量实测加载 5 个批次、74 条作品，跳过 57 条广告或图集及 2 条已下载视频，新增下载 15 条视频，最终收到末页信号并报告 `source_exhausted`。上述各路径新增的 19 个文件均通过大小、MD5、音视频轨道和开头/中间/结尾抽帧解码检查。验收汇总在 `runs/feature_acceptance.json`。11 项自动化测试覆盖分页末尾、下载期间预取末页、筛选、配置覆盖、去重记录和扩展注册。搜索验证期间曾遇到验证码，由使用者手动完成后继续成功采集。

全量模式只在接口明确结束时报告完成；实际大账号是否能完整跑完还取决于该账号可访问范围、平台验证及运行上限。抽帧不等同于逐帧检查全片，验证器不执行音频解码。

本版本支持本机采集并导出任务清单、服务器下载与校验；已在 `./douyin-current-snapshot` 用已有 `shared system environment` 完成 3 条真实视频的探测、下载、MD5、抽帧及重复执行去重测试。操作和限制见 [SERVER_MIGRATION.md](../SERVER_MIGRATION.md)。当前传输仍需显式 SSH/SCP 操作，未实现自动分发、自动回传状态或自动刷新媒体地址。

仍未实现图集下载、评论抓取、音视频转写、断点恢复网页分页和无人值守验证码处理。登录和验证码留在本机，服务器任务不携带 Cookie。

`download_from_page.py` 仍可从保存的 HTML 下载单条作品。原始 `download_douyin.py`、`download_by_urls.py` 是 F2 雏形，当前统一环境未安装 F2，旧入口未完成运行验证，不作为推荐入口。

分享项目时只分发代码、依赖文件、示例和测试，不要分发 `browser_profile/`、Cookie、HAR、`.cache/` 或 `runs/`。这些目录已在 `.gitignore` 中，浏览器配置和原始记录可能含登录凭据或临时签名地址。
