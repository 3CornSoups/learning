# Learning｜学习笔记

按主题整理论文、代码、实验记录和研究笔记，便于人和 AI 助手一起持续维护。目录保持扁平，新增主题直接放在仓库根目录。

## 主题

### [RAG](RAG/README.md)

围绕知识变化下 RAG 的组织、检索和维护，现有四项重点工作：ProStruct-RAG、AURORA、GFM-RAG 和 HyperRAG-IHM。

- [四项 RAG 工作详读](RAG/四项RAG工作详读.md)：逐篇说明问题、方法、数据、实验结论和局限，可直接在线预览。
- [交互式导读](RAG/index.html)：图文对照、共享例子和讨论提纲。
- 原论文、固定版本的作者代码包、Asteria 数据、项目资料及文件校验记录都在 `RAG/` 中。

### [MinimaxH3](MinimaxH3/README.md)

后训练相关工作主题目录。目前作为入口和整理约定，后续笔记、论文和实验结果直接放在该目录下。

## 维护说明

- [维护约定](MAINTENANCE.md)：目录深度、命名、索引更新、资料来源与 AI 协作规则。
- [AI 助手规则](AGENTS.md)：本仓库内协助维护时应遵守的简要指引。

## 当前结构

```text
learning/
├── README.md
├── MAINTENANCE.md
├── AGENTS.md
├── RAG/
└── MinimaxH3/
```

新主题也直接在根目录新建一个简短、可读的目录名，并在本文件补充入口。除非资料本身确实需要，不要再套多层分类目录。
