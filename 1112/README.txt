1112｜周五讨论资料包
整理日期：2026-11-12。按当前日期，周五为 2026-11-13。

入口：四项 RAG 工作逐篇详读见 四项RAG工作详读.md；交互式图文导读见 index.html。所有本地链接均为相对路径，请整体移动本文件夹。

papers/：老师指定的三篇 ACL 论文，以及 GFM-RAG 原论文和后续 G-reasoner 论文，共五篇。
sources/：作者网页快照、README、BibTeX。快照并非完整离线镜像。
code/：两个确认关联的作者仓库 ZIP（以提交哈希固定）；部分文档已解出。
  kapipe: 89aaeb94653698a13159bfc3168091c8527eb895
  gfm-rag: b3e43219c49929da505244df4f0ba54c0947e4c4
  kapipe_89aaeb9_docs/experiments/prostruct_rag_pipeline_emnlp2026/ 下另含作者实验脚本、配置、Asteria 数据及示例数据。
assets/：从论文渲染的原始页面 PNG，以及网页检查截图。
extracted/：原论文文本提取，供检索；公式、表格和特殊字形请以 PDF 为准。
manifest.json / manifest_extra.json：下载地址、日期、文件大小、SHA-256 和失败记录。
collect.py / collect_extra.py：下载记录所用脚本（本机 Python 3.11 + pypdf，使用 curl.exe）。

范围与缺口：
- AURORA、HyperRAG-IHM 本次未确认作者代码仓库；不使用同名项目替代。
- AURORA 官方页列出的 checklist 返回 404，未下载成功。
- 不包含大型模型权重及外部完整基准数据；未安装、运行或复现研究代码。
- 网页数字由原文核对，研究设想和疑问明确标注；四项工作不能直接横向排名。
- 讨论笔记保存在当前浏览器，重要内容使用“导出笔记 TXT”备份。
