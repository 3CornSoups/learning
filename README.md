# RAG 研究资料整理

围绕“知识持续变化时，RAG 如何组织、检索和维护知识”，整理了四项相关工作，供阅读和讨论使用。

## 从这里开始

打开 **[Markdown 详读文档](1112/四项RAG工作详读.md)** 可直接在线预览或按章节阅读，逐篇梳理论文的问题、原始方法、实验结果和局限。也可以打开 **[交互式中文导读](1112/index.html)** 查看图表和例子。保留 `1112/` 目录结构即可正常使用其中的论文、图片和源码链接。

## 收录内容

| 工作 | 关注点 | 资料 |
| --- | --- | --- |
| ProStruct-RAG | 用命题间的时间与逻辑关系处理更新和冲突事实 | [论文](1112/papers/01_ProStruct-RAG.pdf) · [作者代码与 Asteria 数据](1112/code/kapipe_89aaeb9.zip) |
| AURORA | 让检索索引适应新主题与分布漂移 | [论文](1112/papers/02_AURORA.pdf) |
| GFM-RAG | 用图基础模型检索多跳证据，并迁移到新语料 | [论文](1112/papers/03_GFM-RAG.pdf) · [作者代码](1112/code/gfm-rag_b3e4321.zip) |
| HyperRAG-IHM | 增量维护超图关系，减少新文档到达后的重建成本 | [论文](1112/papers/04_HyperRAG-IHM.pdf) |

另收录 G-reasoner 论文，帮助理解 GFM-RAG 项目线的后续版本：[补充论文](1112/papers/05_G-reasoner_related.pdf)。

## 目录

- `1112/index.html`：交互式中文阅读导读。
- `1112/papers/`：四项工作相关的原论文，以及 G-reasoner 补充论文。
- `1112/code/`：按固定提交保存的 KAPipe 与 GFM-RAG 作者源码包；部分文档和 ProStruct-RAG 实验资料已解出。
- `1112/sources/`：ACL Anthology、项目文档、README 和 BibTeX 来源快照。
- `1112/extracted/`：论文文字提取版本，检索方便；引用表格、公式和特殊符号时请回到 PDF 核对。
- `1112/assets/`：原论文页面图像及导读预览。
- `1112/manifest.json`、`1112/manifest_extra.json`：来源、下载日期、文件大小和 SHA-256 校验值。
- `1112/README.txt`：资料包的详细范围和使用说明。

## 阅读提示

四项工作分别处理事实关系组织、索引适应、图检索和超图维护。它们的任务、数据集和评价指标不同，导读中的数值不构成统一排行榜。AURORA 和 HyperRAG-IHM 的作者代码仓库在整理时未能确认，因此没有用同名项目替代。这里也不包含大型模型权重或所有外部基准数据，代码包尚未运行或复现。

导读中已将论文报告的结果与讨论设想区分开。讨论笔记保存在使用时的浏览器本地存储；需要跨设备保留时，请使用页面里的“导出笔记 TXT”。

## 原始论文入口

- [ProStruct-RAG · ACL Anthology](https://aclanthology.org/2026.emnlp-main.294/)
- [AURORA · ACL Anthology](https://aclanthology.org/2026.findings-acl.495/)
- [GFM-RAG · arXiv v3](https://arxiv.org/abs/2502.01113v3) · [作者项目文档](https://rmanluo.github.io/gfm-rag/latest/)
- [HyperRAG-IHM · ACL Anthology](https://aclanthology.org/2026.emnlp-main.898/)
