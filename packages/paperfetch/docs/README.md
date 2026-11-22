# SPC 文档索引

SPC 是 Linux-first 科研资源 CLI。公共 Agent 架构只有 `Skill -> CLI -> 领域服务`；不存在
SPC MCP 或 `agent-guide`。命令与参数的最终权威是实时 `spc --help` 与 `spc schema`；
文档只解释语义、边界和设计决策。

## 产品契约

- [SPC 2.0 架构基线](SPC2.0架构与迁移基线.md)：产品边界、运行环境、模块、配置、Seed Pack 与测试不变量。
- [CLI 与 Skill 契约](SPC2.0CLI与Skill重构契约.md)：命令树、`spc.result.v2`、Job、stdout/stderr。
- [Seed Pack 契约](智能体种子包契约.md)：Seed Pack 命令、目录结构与 `papers.jsonl` 事实源。

## 论文、元数据与下载

- [数据源接口策略](数据源接口策略.md)：默认与可选元数据源、OA/PDF 规则与失败原因。
- [元数据调度与缓存架构](元数据调度与缓存架构.md)：API Key 池、429/5xx 调度、版本化缓存。
- [论文全文下载架构](论文全文下载架构.md)：合法下载路线、PDF 身份校验与失败诊断。

## 公共数据

- [公开归档数据集获取](公开归档数据集获取.md)：Zenodo / Figshare 记录检查、远程 ZIP inventory 与续传下载。

冲突优先级：当前代码与实时 `spc schema` > `AGENTS.md` > 本目录文档。
