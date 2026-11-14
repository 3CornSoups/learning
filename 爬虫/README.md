# 爬虫项目集

本目录整理了 Bilibili 下载/抓取工具、两份抖音代码快照，以及 MediaCrawler 上游项目参考。每个子目录都是独立工程，依赖、入口和适用平台不同；先读对应项目说明再运行。

## 项目导航

| 项目 | 内容 | 备注 |
| --- | --- | --- |
| [bilibili](bilibili/) | 搜索、链接解析、批量下载、并发下载和统计工具 | Cookie/登录态由使用者本机配置；不含个人任务 ID、下载视频或运行报告 |
| [douyin-current-snapshot](douyin-current-snapshot/) | F2 链接下载、服务端下载流程与验证说明 | 代码快照；原始机器路径已改成相对路径，浏览器启动脚本和登录态未发布 |
| [douyin-shared](douyin-shared/) | 共享版本的抖音抓取与下载流程 | 与 current snapshot 分开保存，不能默认视为同一版本 |
| [MediaCrawler](MediaCrawler/) | 多平台开源采集框架参考 | 保留上游许可证；使用前阅读其许可证和平台规则 |

## 安全与复现

- 未纳入 Cookie、浏览器 profile、HAR、下载媒体、缓存、运行日志、虚拟环境或凭据。
- Cookie、代理密钥、数据库密码由运行者通过本机配置提供；不要提交真实值。
- 抖音 current snapshot 的原始验证文档包含的部署目录不属于本仓库；快照内容与历史环境/运行结果不能混为一谈。
- 这里整理的是代码和已有说明，没有在此发布目录中重新运行爬虫，也不据此声称外部平台接口当前可用。
- MediaCrawler 含其原 LICENSE（非商业学习许可）；其余独立项目的来源与许可仍应以对应文件、原始作者说明为准。

## 建议阅读顺序

1. 先看本页，确认要使用的是哪个独立项目。
2. 抖音项目查看 readme.md、F2 下载优化/迁移说明和 server/README.md。
3. Bilibili 查看 使用说明.md、批量下载说明与抓取统计说明。
4. MediaCrawler 查看 README.md 和 LICENSE。
