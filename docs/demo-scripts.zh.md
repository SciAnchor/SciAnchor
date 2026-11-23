# SciAnchor 宣传演示脚本

本文档用于准备 GitHub 主页展示素材。目标不是完整教程，而是在 60-90 秒内让观众快速理解 SciAnchor 的核心价值：

> SciAnchor 把 AI agent 的科研动作变成有证据、有过程、有状态、可接续的研究资产。

建议产出两条短视频：

- `demo-cli.mp4` / `demo-cli.gif`：CLI + agent 工作流
- `demo-zotero.mp4` / `demo-zotero.gif`：Zotero 阅读工作流

两条视频共用同一个研究问题，减少理解成本：

```text
robust budget pacing for online advertising
```

## 视觉原则

- 视频节奏快，但每个镜头只表达一个意思。
- 终端、Zotero、Codex 画面都使用真实界面，不使用纯概念动画替代产品。
- 所有命令和提示词尽量短，避免观众在 3 秒内读不完。
- 字幕强调价值，不复述屏幕上的命令。
- GitHub 主页中使用短 GIF/WebP 预览，高清 MP4 可放到发布页或文档资源中。

## 演示 1：CLI / Agent 端

### 核心信息

RH 是科研 agent 的 harness 层。它把 topic、paper pool、orchestrator 阶段、artifact 和 provenance 固化下来，让一次性聊天变成可接续的研究状态。

### 推荐时长

75-90 秒。

### 画面准备

- 终端窗口，位于仓库根目录。
- 可选：旁边打开 Codex/Claude Code 窗口，用于展示 agent 提示词。
- 最好使用一个干净演示数据库或可复现的演示数据，避免真实私有研究数据出镜。

### 镜头脚本

| 时间 | 画面 | 操作 / 屏幕内容 | 字幕 / 旁白 |
|---|---|---|---|
| 0-6s | GitHub 主页顶部或终端标题 | 展示 SciAnchor 标识和一句定位 | 普通 agent 能回答科研问题；RH 让这些回答留下证据、过程和状态。 |
| 6-14s | 终端 | `rh --json doctor` | 先确认本地环境、模型路由和 RH 数据库可用。 |
| 14-24s | 终端 | `rh topic init "robust budget pacing for online advertising"` | 每个研究方向先进入一个可追踪的 topic，而不是散落在聊天记录里。 |
| 24-38s | 终端 | `rh paper search "robust budget pacing online advertising" --topic-id 1 --auto-ingest` | 检索结果进入 paper pool，后续阅读、筛选和写作都能回到同一个研究空间。 |
| 38-48s | 终端 | `rh paper list --topic-id 1` | paper pool 是可复用资产，不是一次性搜索结果。 |
| 48-60s | 终端 | `rh orchestrator init --topic "robust budget pacing for online advertising" --mode standard` 和 `rh orchestrator status --topic "robust budget pacing for online advertising"` | orchestrator 记录当前阶段、门控状态和下一步动作。 |
| 60-75s | Agent 窗口 | 输入提示词：`基于这个 topic 的 paper pool，提取 claims，识别 research gaps，并记录 artifacts。` | agent 负责执行研究动作，RH 负责把证据、产出和 provenance 留下来。 |
| 75-86s | 终端 | `rh topic overview --topic-id 1` 和 `rh orchestrator artifacts --topic-id 1` | claims、gaps、baselines、草稿和 review 都可以回放、审查、接续。 |
| 86-90s | 收尾字幕 | `证据 + 来源链 + 可接续研究状态` | SciAnchor 是给 AI agent 使用的持久科研工作区。 |

### 可直接复制的演示命令

实际录制时建议先确认 topic id，必要时把 `1` 替换为真实 id。

```bash
rh --json doctor
rh topic init "robust budget pacing for online advertising"
rh paper search "robust budget pacing online advertising" --topic-id 1 --auto-ingest
rh paper list --topic-id 1
rh orchestrator init --topic "robust budget pacing for online advertising" --mode standard
rh orchestrator status --topic "robust budget pacing for online advertising"
rh topic overview --topic-id 1
rh orchestrator artifacts --topic-id 1
```

### Agent 提示词

```text
请阅读 docs/agent-guide.md。
基于 topic "robust budget pacing for online advertising" 的 paper pool，
提取关键 claims，识别 research gaps，并把关键产出记录为 RH artifacts。
每个结论都要保留来源和可审查的证据链。
```

### GitHub 主页一句话

```text
CLI / Agent 工作流：把一个研究问题变成可追踪的 topic、paper pool、阶段产出和 provenance。
```

## 演示 2：Zotero 端

### 核心信息

Zotero 是真实阅读现场，RH 是背后的研究记忆。用户可以从文献、文献集合、PDF 选中文本和截图发起 RH 对话；写入 Zotero 或同步 RH 资产时走确认卡，不让模型文本直接修改本地文献库。

### 推荐时长

75-90 秒。

### 画面准备

- Zotero 已安装 RH 面板插件。
- 本地 RH API 可用，或确认插件能自动启动本地服务。
- 准备一个演示文献集合，例如 `Research Harness / 自动科研`。
- 准备 1-3 篇已同步或可匹配到 RH paper/topic 的论文。
- 如果要展示 PDF 附件动作，确保 RH 已有安全的本地 `pdf_path`。

### 镜头脚本

| 时间 | 画面 | 操作 / 屏幕内容 | 字幕 / 旁白 |
|---|---|---|---|
| 0-7s | Zotero 文献库 | 展示文献集合、文献列表和右侧 `RH` 入口 | 很多科研工作不是从终端开始，而是从 Zotero 里的一篇论文开始。 |
| 7-18s | Zotero 右侧 RH 工作区 | 选中一个文献集合，点击 `RH` | RH 可以从当前 Zotero 上下文启动研究工作区。 |
| 18-32s | RH 面板 | 输入：`帮我找到最开始的 5 篇种子论文` | 空文献集合也可以成为研究入口：先搜索候选论文，再让人确认。 |
| 32-44s | RH 动作预览 | 展示候选论文预览卡，点击确认 | 写入动作先预览，确认后才同步到 RH 和 Zotero。 |
| 44-56s | 选中一篇论文 | 输入：`这篇论文对自动科研主题有什么启发？` | RH 把 Zotero 条目映射到 RH paper/topic，再交给 Codex 生成上下文回答。 |
| 56-68s | PDF 阅读器 | 选中一段文字，追加到 RH 问题 | 选中文本、截图和人工阅读现场可以直接进入下一轮研究对话。 |
| 68-80s | RH 面板 | 输入：`基于这段内容，提取核心 claim 和局限。` | 阅读不再只是注释；它会变成可追踪的 claim、note 和后续 evidence。 |
| 80-88s | RH 面板确认卡 | 输入：`把这个主题里精读过的 3 篇论文导入当前目录`，展示确认卡 | 同步和导入由 RH 后端生成受保护动作，用户确认后执行。 |
| 88-90s | 收尾字幕 | `Zotero 是阅读现场，RH 是研究记忆。` | Research Harness 连接阅读、agent 和 provenance。 |

### 可直接复制的演示提示词

```text
帮我找到最开始的 5 篇种子论文
```

```text
这篇论文对自动科研主题有什么启发？
```

```text
基于这段选中文本，提取核心 claim、关键假设和局限。
```

```text
把这个主题里精读过的 3 篇论文导入当前目录
```

```text
下载并附加 PDF 到当前条目，先 dry-run，确认后 apply
```

### GitHub 主页一句话

```text
Zotero 工作流：从正在阅读的论文出发，带着本地上下文提问，并通过确认卡把 RH 动作同步回文献库。
```

## GitHub 主页展示区草案

等视频或 GIF 生成后，可以在 GitHub 主页的产品特点之后加入：

```md
## 演示

| CLI / Agent 工作流 | Zotero 阅读工作流 |
|---|---|
| ![SciAnchor CLI 演示](docs/assets/demo-cli.gif) | ![SciAnchor Zotero 演示](docs/assets/demo-zotero.gif) |
| Topic → paper pool → orchestrator → artifacts | Zotero 条目 → RH 对话 → 确认后同步 → provenance |

SciAnchor 既接住 agent 的执行过程，也接住研究者的阅读现场。
```

## 后期制作建议

### 成品规格

- GitHub 主页预览：`1280x720`，10-20 秒循环 GIF/WebP，尽量小于 20 MB。
- 完整宣传视频：`1920x1080` MP4，60-90 秒。
- 字幕：中文优先；如果要兼顾国际传播，再另做英文字幕版本。

### 剪辑节奏

- 每个镜头保留 3-8 秒。
- 命令执行慢时，用 jump cut 或加速，不展示长时间等待。
- 对关键 UI 区域做轻微 zoom，不要频繁大幅缩放。
- 失败、调试日志、私有路径、真实 API key、私人 Zotero 条目不要出镜。

### 推荐片头 / 片尾文案

片头：

```text
SciAnchor
让 AI agent 的科研过程有证据、有来源链、可接续
```

片尾：

```text
从检索、阅读和观点提取
到 provenance、artifact 和可复用研究状态
```

## 待确认事项

- CLI 演示是否使用真实模型运行，还是使用可复现的无密钥/预录制演示。
- Zotero 演示是否录制真实 Zotero 插件，还是先用本地测试库录制。
- GitHub 主页预览使用中文、英文还是双语字幕。
- 是否同时发布完整 MP4、短 GIF 和封面图。
