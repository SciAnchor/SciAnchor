# npj 系列：计算方法类论文 + 特刊范围合规手册

Target venue family: **Nature Portfolio npj series**（npj Digital Medicine / npj Precision Oncology /
npj Parkinson's Disease / npj Breast Cancer / …）
适用体裁：以**计算模型或方法为核心**、落在某个生物医学任务上的论文。
证据快照日期：2026-08-27。

---

## 0. 常规（standing rule，除非当次任务另有指定）

只要目标期刊是 npj 系列中的任意一本，**默认同时启用下面几条**，不需要每次再问：

1. **计算文风格（method-core）。** 论文的主张形态是"一个有名字的模型/框架/算法解决一个可形式化的
   任务"，临床领域提供任务定义、数据与 implications，而不是把论文写成关联性/流行病学实证研究。
   判据一句话：**能不能定义"输入 → 输出 → 可度量的正确性"？** 能，就写方法类。
2. **特刊范围合规（collection scope gate）。** 选题必须**在正式开写之前**被证明落在目标 collection
   的 key themes 之内，并把命中的 theme 逐条写进选题记录。范围不符是 npj 特刊最常见的 desk reject
   原因，而它是零成本可避免的。
3. **临床前置（clinical-forward packaging）。** 计算方法是**内核**，但对外的每一层表达——题目、摘要、
   Introduction 开头、Results 的主结果句、Discussion 的落点——都必须是**临床语言**，并且要真的证明
   临床意义，而不是声称临床意义。见 §6.3 的硬约束：题目里不出现架构词；摘要开篇是**当前被做坏的那个
   临床决策**及其代价；主结果除判别度外必须给**临床效用**（净获益/决策曲线、提前量、改变的处置比例、
   可省下的检查）；结尾落在"诊疗流程怎么变"。
   反过来说：架构、损失函数、消融、复杂度全部放进 Methods 与正文，一个都不能少（§4），但它们不出现
   在包装层。**内核照写不误，外壳只讲临床。**
4. **开源数据门。** npj 文**必须**有可公开获取的数据可用（公开库 / 开放许可
   队列 / 可二次分析的已发布语料，能在 Data Availability 里点名引用）。开写、出题、写摘要**之前**
   先核这条。找不到 → **停**，给出对目标 topic **尽可能小的一处调整**（换终点、
   换人群、换治疗背景、换模态，使公开数据对得上），回来和用户商量，**不得自行推进、不得用纯
   模拟队列顶上继续写**。微调仍须过 §1.2 特刊范围门。

这四条覆盖 npj 全系列。只有当用户在当次任务里明确要求别的体裁（综述、Perspective、Comment）时，
计算文/临床前置才失效。特刊默认只在用户明确说投正刊、换 Collection、或不进特刊时才摘掉。
开源数据门不因体裁或「不进特刊」而失效。

---

## 1. 特刊范围门（collection scope gate）

### 1.1 取证方式

`www.nature.com` 对 `WebFetch` 返回 303 到 `idp.nature.com`，抓不到正文。改用带浏览器 UA 的 curl：

```bash
curl -sL -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36" \
  "https://www.nature.com/collections/<id>" | python3 -c "
import sys,re,html
t=sys.stdin.read()
t=re.sub(r'<script.*?</script>','',t,flags=re.S); t=re.sub(r'<style.*?</style>','',t,flags=re.S)
t=re.sub(r'<[^>]+>',' ',t); print(re.sub(r'\s+',' ',html.unescape(t))[:8000])"
```

同一 collection 下还要抓 `/participating-journals`（决定实际投哪一本）、`/guest-editors`。
**参与期刊决定格式与体裁上限，collection 只决定选题范围。**

### 1.2 合规判定

把 collection 的 key themes 抄成清单，对每条给出本选题的命中方式：`hit` / `partial` / `miss`。
准入线：**≥3 条 `hit`，且其中至少 1 条是该 collection 标题里的核心词**。
只靠 `partial` 拼出来的匹配等于没匹配——那是把一篇不相干的稿子硬塞进特刊，审稿人一眼看得出。

命中不足时的正确动作是**改造选题的模态组合或任务定义**去真正落进范围，而不是在摘要里加范围关键词。

### 1.3 建档新 collection

目标是某个特刊时，在这里按 §1.1 的取证方式建档：collection 名称、参与期刊、截止日期与 key themes
原文清单，再按 §1.2 逐条打分。

---

## 2. npj 系列格式规格

npj 系列在线出版、全 OA，**不设硬性字数上限**，但按下表写是安全线（Article）：

| 元素 | 口径 |
|---|---|
| 正文 | ≤4,000–4,500 词（不含摘要、Methods、参考文献、图注） |
| 摘要 | 约 150 词，**不分小标题、不带引用** |
| 图表 | ≤10 个 display item |
| 参考文献 | 约 60 条 |
| 结构 | Introduction → Results → Discussion → Methods，Results/Methods 下设主题小标题 |
| SI | 合并为**单独一个 PDF** |

其他体裁：Brief Communication 摘要约 70 词（3 句）、Perspective 正文 ≤3,000 词、Matters Arising
≤1,200 词 / ≤15 条引用。

参考文献用 Nature 风格；URL 在正文里以括号引用，不进编号列表；致谢与基金不作为编号引用；不用脚注。

**注意**：以上是 npj series 通用模板口径。具体某本刊的 content-types 页可能微调，**定稿前按参与期刊
自己的页面复核一次**。

---

## 3. EAG "Nature 级模版" 锚点

npj 稿件的 form 不从 npj 自身学到顶——npj 是 **venue_fit**（教格式与合规），**ceiling** 要从
Nature Medicine / Nature Communications / Lancet 系拿：

> ceiling 与 venue_fit 在"打磨程度"上冲突时，schema 方向听 ceiling，版式/节序/报告清单听 venue_fit。

**医学 ceiling + npj venue_fit 锚点池**（均已在 RH pool 内，可直接 `rh paper link`）：

| ID | 刊 | 角色 |
|---|---|---|
| 4683 | Nature Medicine 2022 | 多模态生物医学 AI 的框架级 ceiling |
| 3317 | Nature Medicine 2024 | 基础模型 / 表征学习叙事 ceiling |
| 6582 | Nature Communications 2025 | 开发—验证—真实世界落地三段式 ceiling，患者 vignette 图版 |
| 6599 | BMJ 2024 | TRIPOD+AI，报告清单的 statute |
| 6593 | npj Digital Medicine 2022 | RCT 溯源 + 多模态个体化治疗，病理图谱 |
| 6602 | npj Digital Medicine 2025 | **深度多模态状态空间融合**——连续/序列建模类最近锚点 |
| 6603 | npj Digital Medicine 2025 | 多模态生存预测 + 独立 error analysis 节 |
| 3310 | npj Digital Medicine 2025 | 命名框架（HONeYBEE）+ 嵌入式可扩展多模态 |
| 3312 | npj Digital Medicine 2025 | 临床信息 prompt 融合 |
| 3315 | npj Digital Medicine 2025 | **STD-Net**——纯方法（解耦网络）类的 npj 范例 |

**执行方式**（不要凭印象仿写，跑引擎）：

```bash
rh paper link <ID> --topic <topic> --relevance high     # 把上表锚点挂进新 topic
rh exemplar curate --topic <topic> --unit-type abstract --min-quality 7 --max-papers 8
rh exemplar plan   --topic <topic> --unit-type abstract --reuse-pack --target "<本文方法与贡献>"
rh exemplar curate --topic <topic> --unit-type skeleton  # 章节骨架同理
```

`exemplar plan` 产出的是 **form-only** 的逐句 element 序列（problem→problem→method×3→
validation×2→result→impact），照它落笔；`exemplar_critique` 的 n-gram 门保证不抄措辞。

---

## 4. 计算文体裁契约（method-core delivery bar）

缺任意一条即视为未达交付线：

1. **命名方法**——模型/框架有专名，可被一句话复述（对齐 3310 HONeYBEE、3315 STD-Net）。
2. **问题形式化**——输入、输出、损失/目标、评价指标写成可计算的定义，不是"我们用了深度学习"。
3. **架构贡献**——至少一个结构性主张（融合方式、时间建模、条件化机制），而不是拼接现成编码器。
4. **≥2 个真实队列**：开发集 + 时间/机构分离的内部测试集 + **独立外部验证队列**。
5. **基线分层**：临床风险评分 / 单模态 / 早融合 / 晚融合 / 同族先进方法，逐层给。
6. **消融**：每个被声称的组件都要有"去掉它掉多少"的对照。
7. **鲁棒性**：模态缺失（modality dropout）、采样不规则、设备与站点差异、亚组一致性。
8. **复杂度与效率**：参数量、推理时延、训练成本——计算文的必备节，医学作者最常漏。
9. **可及性与部署**：可解释性、公平性、失败模式，对齐特刊 theme 9。

领域（肿瘤、脊柱、神经）提供任务、数据与 implications；主张形态始终是方法。

---

## 5. 医学双线门（dual bar）

计算文风格不豁免医学模块。以下为所有医学计算方法稿件的硬规则：

| 规则 | 内容 |
|---|---|
| MED-COHORT-FLOW | 早期给 CONSORT 式队列流程图（主文或 ED） |
| MED-VIGNETTE-PLATE | 主文要有代表性患者多联图版：情境 + 模型输出 + 参考结局 |
| MED-FAIL-GALLERY-MAIN | 成功与失败同版，或独立 FP/FN 画廊 |
| MED-ERROR-SECTION | "Error analysis" 作为 Results 的标题节并配图，不是 Limitations 里的形容词 |
| MED-CHECKLIST-LIVE | 诊断/预后模型点名并**填满** STARD / TRIPOD+AI，清单进 SI |
| MED-SI-SECOND-STAGE | 必须有 SI 文件并被正文逐处引用；**禁止"30+ 页正文 + 零 SI"** |
| MED-ABLATION-ISO | 组件移除 ↔ 指标下降的表/图 |
| MED-OPERATING-POINT | 涉及筛查/诊断时声明敏感度—特异度工作点 |
| MED-IDENTIFICATION-MATCH | 主张语气 ≤ 设计强度；观察性反事实不能写成治疗获益 |
| MED-NO-KEYWORD-CASE | 出现 "representative/failure/case study" 字样但无图版定位 = 未完成 |

---

## 6. 题目与摘要形态

### 6.1 题目长度与专名位置（实测）

RH pool 内 64 篇 2022 年后的 npj 题目：

| 指标 | 值 |
|---|---|
| 词数中位数 | **14** |
| p25 / p75 | 12 / 15 |
| 最长 | 18 |
| 专名（`NAME:`）置于题首的比例 | **4 / 64 ≈ 6%** |

结论两条，都与"计算文的本能"相反：

- **12–15 词，超过 18 词就是超纲。** 20 词以上的方法类长题是 CS 会议习惯，npj 不这么写。
- **方法专名默认不进题目，进摘要第三句。** HONeYBEE、STD-Net 是 6% 的少数派。同刊的 CerviPro
  （npj DM 2025，多模态放疗预后）题目里根本没有 "CerviPro"，写的是
  "Multimodal deep learning model for prognostic prediction in cervical cancer receiving definitive
  radiotherapy: a multi-center study"——**临床任务 + 人群 + 治疗背景 + 设计后缀**。这是 npj 的默认句式。

推荐模板（按临床可检索性排序）：

```
<多模态/监测手段> for <临床决策或终点> in <疾病人群><治疗背景>[: a multicentre <设计> study]
<Predicting/Multimodal prediction of> <临床结局 1> and <临床结局 2> in <疾病>
```

设计后缀（`: a multicentre development and validation study` / `: a multi-center study`）是纯临床加分项，
可把题目推到 16–18 词，仍在实测范围内。

**题目里禁止出现的词**：架构名词（transformer、encoder、state-space、attention、fusion architecture）、
损失函数、"framework"、"novel"。`multimodal` 可以留——它是特刊的核心词，也是临床读者认的词。

### 6.2 摘要元素序列（EAG 实测）

约 150 词、无小标题、无引用：

`problem(临床需求) → problem(建模缺口) → method(命名与总体形态) → method(区分性技术点 1) →
method(区分性技术点 2) → validation(队列与终点) → validation(基线与消融) → result(带 CI 的主结果) → impact`

### 6.3 临床前置硬约束（§0 规则 3 的落地）

| 位置 | 必须是 | 不能是 |
|---|---|---|
| 第 1 句 | **当前被做坏的那个临床决策**，以及做错的代价（病死率、治疗中断、不必要手术/随访） | "多模态数据日益丰富…" |
| 第 2 句 | 临床上信息为什么用不起来（分散、异步、各看各的） | 模型层面的技术缺口 |
| 第 3 句 | 方法专名 + **一句话讲它让临床医生能做什么** | 架构描述 |
| 第 4–5 句 | 区分性技术点，仍用临床后果表述（"把真实迷走变化和日常活动分开""让剂量可被改动以看风险怎么走"） | 编码器、条件化、潜变量 |
| 结果句 | 判别度 + CI + 外部验证，**再加至少一项临床效用**：决策曲线净获益 / 提前量（天、月）/ 改变处置的患者比例 / 可省下的检查比例 | 只有 AUC 和 Δ 基线 |
| 末句 | 诊疗流程怎么变 + 需要前瞻验证 | "本方法可推广到其他任务" |

"证明临床意义"与"声称临床意义"的分界就是**结果句里那项临床效用指标**。没有它，评审读到的就是一篇
被塞进医学期刊的方法论文。决策曲线分析（net benefit）是最省事、最被 npj DM 接受的那一项，Methods
里加一节即可。

其余：定义清所有专名与终点；预测与因果分开说；判别度之外必须给校准与外部验证；不写泛化的宏大声明。

---

## 7. 交付前自查

- [ ] Collection key themes 逐条打分，≥3 条 `hit` 且含核心词
- [ ] **开源数据门：主分析用的队列/模态能点名公开源；找不到则停，只提交最小改题方案，不推进**
- [ ] 参与期刊已确认，格式按该刊 content-types 复核
- [ ] EAG `exemplar_pack` / `exemplar_plan` 已落盘，摘要与骨架按 plan 的 element 序列写
- [ ] **题目 12–15 词（≤18），无架构词，方法专名不在题首**
- [ ] **摘要第 1 句是被做坏的临床决策及其代价；结果句含至少一项临床效用指标；末句落在诊疗流程**
- [ ] §4 九条计算文契约逐条可指认（内核不因临床包装而缩水）
- [ ] §5 十条医学双线门逐条可指认，尤其 SI 与 case-trace
- [ ] 署名占位 + CRediT 按 `CLAUDE.md` 规则生成，角色按本文实际工作重分配
- [ ] 摘要 ≈150 词、无引用；正文 ≤4,500 词；display item ≤10

