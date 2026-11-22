# 参考数据说明（paperfetch 公开版）

本目录只随包分发**可公开再分发**的期刊/会议目录数据。商业或来源受限的评价数据
（Clarivate JCR、中科院期刊分区与预警名单、XR 分区等）以及由它们派生的期刊主库
不随公开版分发；需要时由用户自行准备并通过配置接入。

## 一、随包分发的数据

| 文件 | 内容 | 来源与许可 |
| --- | --- | --- |
| `ccf_ranks_2026.json` | CCF 推荐国际学术会议和期刊目录（A/B/C） | 中国计算机学会公开发布的目录，条目链接至 dblp |

`spc paper search` 的 `ccf_rank` 字段与 `--ccf-rank` 过滤只依赖 `ccf_ranks_2026.json`。

## 二、用户可自行提供的数据

| 环境变量（也可写入 `spc.toml` 同名键） | 期望内容 | 影响的能力 |
| --- | --- | --- |
| `SPC_JOURNAL_MASTER_DB` | 期刊主库 SQLite 文件路径 | 检索结果中的 `cas_zone`、`paper search --cas-zone` 过滤 |

期刊主库需包含表 `journal_records(normalized_name TEXT PRIMARY KEY, original_name TEXT, facts_json TEXT)`，
`facts_json` 为 JSON 对象，至少包含 `journal_name`，分区写在 `cas.zone`（1–4）与
`cas.top_journal`（布尔）中，例如：

```json
{"journal_name": "Nature", "normalized_name": "nature", "cas": {"zone": 1, "top_journal": true}}
```

请确认你有权使用所提供的数据（例如机构订阅的中科院分区表 / JCR）。

未配置时的行为：

- 论文检索、反查、下载、解析等功能照常工作；`cas_zone` 字段为 `null`。
- `spc paper search --cas-zone ...` 返回 `rejected`，错误码 `cas_zone_not_configured`，
  不会静默返回空结果。
- `spc doctor` 中 `paper.metadata.journal_master` 显示 `unknown`（未配置，非阻断项）；
  配置了但文件缺失或格式不对时显示 `wrong`。
