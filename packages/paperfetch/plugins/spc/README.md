# SPC Codex Plugin

该插件只负责安装 SPC Skill。SPC 的唯一执行入口是 `spc` CLI；插件不提供 MCP、应用服务或
第二套业务逻辑。

插件根目录不得包含 `.env`、Token、Cookie、代理认证或下载数据。Skill 使用 `spc schema`
查询当前命令契约，`spc schema config` 查询配置字段。

在仓库根注册本地 marketplace 并安装：

```text
codex plugin marketplace add .
codex plugin add spc@paperfetch
```

`scripts/spc_preflight.py` 在不输出任何配置值的前提下检查解释器、`spc version`、
`spc schema` 与 `spc doctor` 是否可用。修改 Skill 后运行
`tests/test_codex_plugin.py` 与 `tests/test_skill_contract_v1.py`。
