# Research Harness 文档首页

Research Harness 是面向长周期 AI 科研 agent 的执行与状态层。它把文献检索、
论文精读、claim 提取、gap 分析、实验设计和基于证据的写作连接成一条可持续、
可审查、可恢复的研究工作流。

## 先看什么

如果你第一次接触 RH，建议按这个顺序阅读：

1. [仓库首页 README](../README.md)：先建立整体心智模型。
2. [中文快速开始](quickstart.zh.md)：完成安装、环境变量配置和 doctor 检查。
3. [Agent 使用手册](agent-guide.md)：让 Codex / Claude Code / Cursor 真正跑起来。
4. [论文管理规范](paper-management.zh.md)：理解 paper 入库、PDF、topic 绑定等硬约束。
5. [Zotero 集成](zotero-rh-panel.md)：进入当前主推的 researcher-facing 前端。

## 按任务阅读

### 1. 快速开始

- [中文快速开始](quickstart.zh.md) — 安装、环境变量、CLI/MCP 验证
- [English Quickstart](quickstart.md) — 英文版安装说明
- [研究启动清单](research-bootstrap.md) — 新 topic / 新项目的准备动作

### 2. 研究工作流

- [论文管理规范（中文）](paper-management.zh.md) — paper 入库、路径和 topic 绑定
- [Paper Management (EN)](PAPER_MANAGEMENT.md) — 英文版 paper 管理协议
- [Paper Production Workspace Protocol](paper-production-workspace.md) — 论文生产工作区、artifact lineage、public/private 边界
- [Publication Pack](publication-pack.md) — 输出 review-ready / submission-ready 包
- [RH 科研交付协议](research-delivery-protocol.md) — 以 RH 为事实源的 brief → proposal → experiment → paper → review → rebuttal 交付协议
- [Paper Retrieval Pipeline](paper-retrieval-pipeline.md) — 论文检索与获取流程
- [SPC External Acquisition](SPC_INTEGRATION.md) — paperfetch 契约桥接：wants-list 导出、seed pack 导入、PaperVault 本地源、收购缓存与诊断

### 3. Agent 与集成

- [Agent 使用手册](agent-guide.md) — Codex / Claude Code / Cursor 的通用操作规范
- [多工具支持矩阵](tool-support.zh.md) — 哪些宿主 / 代理路径已经真实验证，哪些还只是部分支持
- [Codex 工作流](codex-workflow.md) — Codex 环境、checkpoint、验证方法
- [Cursor Agent](cursor-agent.md) — Cursor 侧的集成说明
- [Python API](python-api.md) — 在 notebook、脚本、pipeline 中使用 RH
- [Topic Knowledge HTTP API](knowledge-http-api.md) — 论文知识库只读 HTTP beta endpoint
- [本地 Agent 工作流](local-agent-workflow.md) — 本地代理 / bridge 的组合方式
- [Zotero RH Side Panel](zotero-rh-panel.md) — Zotero 侧边栏插件与本地 bridge

### 4. MCP / CLI / 可扩展能力

- [MCP 工具与工作流（中文）](mcp-tools.zh.md) — 常用 primitive、编排方式、自然语言驱动
- [ResearchFlowBench](researchflowbench.md) — RH 评测 pack、gold-blind 验证与外部 benchmark registry
- [ResearchFlowBench 优化 backlog](researchflowbench-optimization-backlog-v0.md) — 从 baseline 结果按 RH axis 归因的首个优化清单
- [Showcase Bundle](showcase-bundle.md) — 把公开演示素材收成可校验的证据包
- [Skills 文档](skills/README.md) — RH 自带 skills 的设计与安装
- [插件开发](plugin-guide.md) — 扩展 primitives / gates / backends

### 5. 架构与设计

- [架构总览](architecture.md) — stages、gates、artifacts、storage model
- [架构设计目录](architecture/README.md) — 细分架构文档入口
- [Research Operating Model](research_operating_model.md) — 研究流程抽象
- [Research Toolchain](research_toolchain.md) — 工具链与能力分层
- [Project Map](project_map.md) — 仓库结构导览

### 6. 运维与排障

- [故障排查](TROUBLESHOOTING.md) — 常见错误与修复方法
- [Demo](DEMO.md) — 演示路径与 demo story

## 当前文档组织原则

- **README 负责首页转化**：只讲是什么、为什么、怎么开始。
- **docs 负责承载细节**：安装、工作流、集成、架构、排障分开组织。
- **优先按任务找文档**：先从“我要做什么”出发，再进入实现细节。

## 语言说明

- 仓库默认 README 为中文：[`README.md`](../README.md)
- 英文首页见：[`README.en.md`](../README.en.md)
- 部分深层设计文档目前仍以英文为主，后续逐步补齐中文导航与摘要
