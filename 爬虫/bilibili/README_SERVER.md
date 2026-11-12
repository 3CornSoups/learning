## 2026年11月11日 五并发版本

随机采集入口已默认采用5并发下载。最新命令见 `五并发下载说明.md`，技术报告见 `技术报告_飞书版.md`。

> 抓取条数和耗时统计请看 [抓取统计说明.md](抓取统计说明.md)。普通随机入口也会自动生成 reports/latest.md 和 reports/latest.json。

> 当前完整说明请看 [使用说明.md](使用说明.md)。入口现为任意关键词，默认20条，不再自动使用旧候选快照。匿名实时搜索仍受B站验证限制。

# Bilibili服务器下载工具

服务器目录：./bilibili

代码和依赖已就绪。视频由服务器下载和合并，只保存在服务器。用户已将默认数量调整为5条，视频只写服务器。可用 --limit 或 --count 自行调整。

## 关键词搜索结果随机下载（已实测）

```bash
cd ./bilibili
./run_search_random.sh '奶龙'
```

当前使用 search_candidates_奶龙.json：2026-11-10从B站公开搜索网页取得的前50条不同视频链接快照。服务器从该池随机打乱候选，排除已下载条目、超过300秒的视频、标题不包含“奶龙”的误匹配，再下载5条。它不是全站均匀随机，也不会自动刷新这个快照。

服务器通过分页/播放信息接口重新解析选中视频，优先使用响应自带的HTTPS备用CDN，并采用Range分段下载，不需要本机参与视频解析或下载。

输出目录：bilibili_videos/search_奶龙/

本次运行报告：work/search_resolved/run_report.json

本次成功运行日志：logs/run_20261110_search_random_range.log

下载历史：bilibili_videos/downloaded.txt（以后自动跳过）

### 控制数量、时长和随机种子

```bash
./run_search_random.sh '奶龙' --count 1
./run_search_random.sh '奶龙' --count 2 --max-duration 120
./run_search_random.sh '奶龙' --seed 42
```

--seed便于复现候选打乱顺序；已有下载历史或搜索池变化时，最终选中结果可能变化。每个BV默认只处理P1。连续多次运行会累计增加服务器上的视频。

## 更新搜索池 / 使用其他关键词

直接调用脚本、不传 --candidates-file 会请求B站实时搜索接口：

```bash
.venv/bin/python search_random_bilibili.py '其他关键词' --pool-size 50 --count 2 --max-duration 300 --api-mode --cookies /绝对路径/cookies.txt
```

本服务器匿名搜索接口当前返回412，所以实时搜索尚需有效登录状态或正常访问条件，不能保证Cookie一定解除限制。用户尚未提供Cookie文件；本次已验证的随机下载使用上面的搜索网页快照，无需Cookie。

支持两种Cookie文件，二选一：

- --cookies cookies.txt：Netscape格式文件。
- --cookie-header-file cookie_header.txt：F12复制的单行Cookie请求头值，也可带Cookie:前缀；文件只保存在本人服务器，不要贴到聊天或提交到仓库。

如果Cookie文件存在，可以先执行 chmod 600 文件名 限制权限。脚本只将原始Cookie字符串转换为bilibili.com域的Cookie，不输出Cookie值。

也可以用浏览器搜索新关键词，通过导出书签保存视频链接，再整理为与search_candidates_奶龙.json同结构的候选快照，调用：

```bash
.venv/bin/python search_random_bilibili.py '关键词' --candidates-file 你的候选文件.json --api-mode --count 2
```

## 更换指定视频：编辑链接清单

在服务器VS Code里打开本目录的 bilibili_urls.txt，每行填写一个新视频的完整BV链接或BV号，保存后运行：

```bash
cd ./bilibili
./run_batch.sh
```

默认读取清单前5条；每行一个视频。去掉不需要的旧链接并填入新链接，就能换视频，不必修改Python代码。输入文件保持不变，已下载视频自动跳过。

自定义数量或使用另一份清单：

```bash
./run_batch.sh --limit 10
./run_batch.sh -i other_urls.txt --limit 8
```

也可以直接传入完整BV视频链接或BV号：

```bash
./run_batch.sh 'https://www.bilibili.com/video/BV1r7W861EV5/'
```

上面是有效链接格式示例，已下载记录会跳过，请换成你需要的视频。当前默认使用P1。链接清单入口使用 download_urls_server.py，复用已验证的服务器分页/播放接口和Range下载设置，无需访问被412拒绝的视频HTML页面。

输出目录：bilibili_videos/by_urls/；运行报告：bilibili_videos/urls_run_report.json。

默认跳过超过300秒的视频；要下更长视频，可显式指定秒数：

```bash
./run_batch.sh --limit 5 --max-duration 1800
```

只检查链接、不下载：

```bash
./run_batch.sh --simulate
```

旧的已解析信息入口保留为 run_batch_resolved.sh，不再由 run_batch.sh 调用。原有 download_bilibili.py 文件也保留，但服务器入口推荐使用新的 run_batch.sh。

## 环境

Python 3.12独立环境：.venv/bin/python；FFmpeg使用服务器已有的/usr/bin/ffmpeg。

```bash
.venv/bin/python -m pip check
.venv/bin/python -m pip install -U -r requirements.txt
```

初建环境时使用服务器已有uv补齐隔离环境的pip和依赖，未修改系统Python。视频下载接口属于第三方站点，变化后可能需要调整解析器。
