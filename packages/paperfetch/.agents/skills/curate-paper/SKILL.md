---
name: curate-paper
description: 当用户要用 SPC 精确查询论文、获取并核验开放获取 PDF、解析本地 PDF 或管理 Seed Pack 时使用。
---

# SPC 论文获取

本 Skill 只选择 SPC CLI 并解释 `spc.result.v2`；不实现下载、认证、解析或代理管理。SPC 没有 MCP。

## 运行边界

- 使用安装了 SPC 的那个环境里的 `spc`（源码检出为 `<checkout>/.venv/bin/spc`），
  不要混用不同安装的解释器、密钥文件或状态根。
- 先运行 `spc system preflight --profile <development|production>`。
  参数不确定时读 `spc schema <command>` 或 `spc schema config`。
- 自动化使用 JSON 和 `--no-progress`。不得输出 API Key、Cookie、代理端点、出口 IP 或签名 URL。
- 不点击或绕过 CAPTCHA、Turnstile、MFA、扫码或真人确认。

## 公开结果

只读 `schema status job_id data files results error`。后台任务用 `spc job wait <job_id>` 取得原命令终局。

- `paper search --query <query> --detach`：多源检索候选。
- `paper lookup --doi <doi> --detach`：精确元数据。
- `paper download --doi <doi> --output-dir <dir>`：下载、身份核验并默认解析；`--no-parse` 只取 PDF。
- `paper parse --pdf <pdf> --output-dir <dir> --detach`：无身份绑定的物理解析。
- `seed-pack init|show|add|enrich`：管理 Seed Pack，不手改 `papers.jsonl`。

PDF 成功必须有物理文件、字节、SHA-256 与 `data.download.identity_verified=true`。
`route=local` 只证明缓存文件。paperfetch 不包含机构订阅访问；没有合法开放副本时如实报告失败。

## 失败诊断

先报告 `error.code`、`error.message`、`error.stage` 和 `error.next`。网络类失败再运行：

```bash
spc doctor --probe-traffic-classes --output-format json --no-progress
```

只读 `data.verdict`、`data.checks`、`data.blockers`。代理端点不可达或 407 为已确认原因；
通路检查 ok 只证明探针可达，不代表某篇论文可获取。

SPC 不负责选题、论文评价或科研方法执行。
