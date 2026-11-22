# IP&M 计算类论文：行文手册 / 设计手册 / 设计理念

Target venue: **Information Processing & Management** (Elsevier, ISSN 0306-4573, CCF-B / CAS-Q1, IF≈7.4)
适用体裁：以**计算模型或方法为核心**、并落在某个信息任务或应用领域上的论文。
证据快照日期：2026-08-27；时效线补录 2026-09-06。复现口径见 §1 与附录 A。

---

## 0. 结论与默认规则

**IP&M 的默认体裁就是"计算方法 × 信息任务/应用域"。** 官方 scope 明确列出三类稿件，其中第二类是
"**Methods manuscripts** focusing on the application of novel methods at that intersection"；2024–2026 年
600 篇 research article 的标题分类中，方法/模型类占 **61%**（另有 29% 的"其他"经抽样后仍以方法与系统类
为主），明确的行为/实证类仅 **7%**，综述类 **3%**。

因此对 RH 的规则是：

> **在期刊允许的前提下，面向 IP&M 的选题默认设计为计算方法类论文（method-core），而不是行为实证类论文。**
> 领域内容（创业、体育训练、健康、教育、金融……）作为**任务与数据的来源**进入论文，而不是作为论文的主张形态。
> 只有当研究问题本身无法被形式化为一个可计算任务（例如纯访谈研究、纯政策分析），才退回实证/质性设计。

判断只需一问：**能不能定义"输入 → 输出 → 可度量的正确性"？** 能，就写方法类。

---

## 1. 证据基线（可复现）

| 证据 | 口径 | 结果 |
|---|---|---|
| 期刊 scope 与稿件类型 | Elsevier 官方 Aims & Scope / Guide for Authors | 见 §2.1 |
| 体裁分布 | OpenAlex `primary_location.source.issn:0306-4573`, `publication_year>2023`, `type:article`，600 篇标题正则分类 | 方法 61% / 实证 7% / 综述 3% / 其他 29% |
| 全文解剖 | OpenAlex `is_oa:true` 取 77 条带 PDF 直链，成功下载 31 篇，其中 **12 篇方法类逐节解剖** | 见附录 A |
| 章节字数预算 | PyMuPDF 抽取正文（**已剔除 References**），按顶层编号节切分，9 篇方法类统计 | 见 §3.2 |
| 写作惯例频率 | 12 篇方法类全文正则统计 | 见 §3.4 |

| 桌拒实证 | 众筹/创业方向编辑桌拒案例，逐条核回稿件 | 见 §2.4 |


---

## 2. 准入判据：什么样的计算论文 IP&M 会收

### 2.1 官方 scope（原文要点）

> IP&M publishes cutting-edge original research at the **intersection of computing and information science**
> concerning **theory, methods, or applications** in a range of domains, including but not limited to
> advertising, business, health, information science, information technology marketing, and social computing.

接收的稿件类型：research articles、research survey articles、**research method articles**、
articles addressing **critical applications** of research。

### 2.2 三条准入线（缺一即高危）

1. **方法新颖性**：提出的不是"调参 + 换数据集"，而是一个有名字、有结构、能被复述的模型/框架/算法。
   实测：12 篇方法类中 12 篇都给模型起了专名（TCAN、Coase、3SHNet、SelfCP、HetGWalk…）。
2. **信息任务落点**：任务必须是信息科学意义上的任务——检索、排序、推荐、抽取、分类、预测、
   生成、内容治理、知识组织、用户建模。纯视觉/纯控制/纯生物信号且不接信息任务的，属于跑偏。
3. **含义闭环（implications）**：论文必须回答"这对信息系统的设计与实践意味着什么"。
   实测：方法类论文中出现独立的 *Implications* / *Theoretical and Practical Implications* 节，
   或在 Discussion 下设 *Theoretical implications* / *Practical implications* 子节，是 IP&M 与
   纯 CS 会议最显著的结构差异。

### 2.3 与纯 CS 会议（SIGIR/ACL/AAAI）的三点差别

| 维度 | CS 会议 | IP&M |
|---|---|---|
| 正文长度 | 8–9 页双栏 | **正文 6.6k–19k 词（中位 11.9k）**，单栏 16–48 页 |
| 结尾 | Conclusion 收在提升数字上 | 必须落到 **implications**：对信息系统、平台、从业者意味着什么 |
| 领域交代 | 可以只谈 benchmark | 需要交代任务在真实信息环境中的位置（用户、平台、决策后果） |
| 参考文献 | 40–60 条，偏近三年 | **40–115 条（中位 68）**，APA author–year，含信息科学脉络 |

### 2.4 时效线：四条硬带（2026-09-06 桌拒实证）

一封 IP&M 编辑桌拒信的原话要点：该阶段的研究已有多篇发表；需要用上 state-of-the-art 基线与研究，
**尤其是（如适用）大语言模型**；**必须引用当年文章，而你没有**；建议对照近期 IP&M 文章重看结构与研究层次。

复盘该稿得到四条可量化的带，缺一即高桌拒风险。它们**独立于 §2.2 的三条准入线**：准入线管"是不是一篇
IP&M 论文"，时效线管"是不是今年的 IP&M 论文"。

| 带 | 下限 | 该稿实测 |
|---|---|---|
| **B1 当年引文** | 投稿当年 ≥3 条，近两年（当年 + 前一年）合计 ≥15% | 当年 0 条，近两年 0 条 |
| **B2 近三年引文** | 近三年 ≥30% | 近三年 2/41 = 5% |
| **B3 本刊引文** | 目标刊本身 ≥5 条 | 0 条 |
| **B4 同期基线** | 最强**外部**基线的方法年份在近两年内；领域已转向的技术族（当下即 LLM）**必须**至少一条对照 | 最强外部基线 DistilRoBERTa（2019），零 LLM 对照 |

**B4 的推论（自评陷阱）：排行榜第二名不得是自家消融体。** 该稿主表第二名 Static-Fusion 就是本模型去掉
时序分支的变体，于是"超越 SOTA"实际只是超越自己。判定：主表里非本方法的最高分行，其模型名必须能在
Related work 里指到一篇**外部**文献。

**为什么这四条带值得当硬门：桌拒是"扫"出来的，不是"读"出来的。** 那封信来得很快，语气很消极，
但它点到的每一项都能在几分钟内从稿面上扫到：参考文献最新年份、基线表里的模型名、有没有 Implications 这个
小标题、参考文献里有没有本刊。深层贡献要读完全文才能评价，而桌拒发生在读完之前。**结论：重建一篇被桌拒的
稿子，必须同时赢下可扫层和深层，只补深层是白补。** 可扫层的清单就是 §7.4，量化下限就是本节这四条带。

**B1–B3 的写法**：引文年龄分布是**选题时效的代理指标**，不是排版细节。近三年占比低于 30%，等于向编辑
声明"这个方向我停在几年前"。补引文不能靠往 Related work 尾部堆当年文献，必须让当年文献改变 §1 的
gap 陈述与 §5 的基线名单——否则审稿人一眼看出是补丁。

**B4 的写法**：LLM 对照不是"我们也试了 GPT"。按当下文献的两条收敛路线各给一条：
（a）LLM/大模型嵌入替换旧文本编码器，接下游分类或回归；（b）生成式模型作特征抽取器，接梯度提升树。
两条都跑不出增益时，这个反例本身就是可发表结论，但必须在正文里说清楚。

---

## 3. 设计手册

### 3.1 论文的五个承重件

一篇 IP&M 方法论文由五件事撑起来，缺任何一件都会在审稿中被点名：

1. **可形式化的信息任务**：输入、输出、评价指标写得出定义式。
2. **有结构的方法**：3–5 个模块，每个模块解决 introduction 中列出的一个具体缺陷。
3. **有对照的评估**：真实数据集 + 一组公认 baseline + 消融 + 至少一项"非精度"分析。
4. **含义**：理论含义（对该问题的认识改变了什么）+ 实践含义（谁能拿去用、怎么用）。
5. **可复现**：数据来源可查、代码或参数可得。实测 12 篇中 7 篇正文含 GitHub 链接。

### 3.2 骨架与字数预算（实测，正文不含参考文献）

```
1. Introduction                          808–1,865   (中位 1,150)
2. Related Work / Background             642–2,829   (中位 1,157)
3. Preliminaries / Definitions & Notation  322–1,346 (中位 834，可选)
4. <方法专名>  (Method / Approach / Model) 746–5,411  (中位 2,484)
5. Experiments / Experimental Evaluation 1,037–9,353 (中位 4,105)   ← 全文最大节
6. Implications (Theoretical & Practical)  156–987   (中位 304)
7. Conclusion (and Future Work)            250–650
References                                40–115 条  (中位 68)
```

**关键比例**：Experiments ≈ Method 的 1.5–2 倍。方法写得比实验长，是方法论文的典型失衡。

图表预算（实测）：**图 4–14（中位 8）**、**表 4–14（中位 8）**、**编号公式 3–37（中位 17）**。
第一张图固定是**方法总览图**（overall architecture / framework），出现在 §4 开头。

### 3.3 方法节的设计规则

- **给方法起名**：首字母缩写要能读出来（TCAN、Coase、3SHNet、SelfCP），并在摘要首次出现处展开全称。
- **模块数 3–5**：实测子节形态为
  `Feature Extraction → 核心机制模块 ×2 → Fusion/Prediction layer → Complexity analysis`。
- **每个模块对应 introduction 里的一个 challenge**：challenge ①②③ 与模块 ①②③ 一一对应，读者能连线。
- **必写复杂度分析**：`Time complexity analysis` / `Computational Complexity Analysis` 作为方法节最后一个子节，
  实测 12 篇中 8 篇有效率或复杂度分析。
- **符号表**：Preliminaries 节给定义与记号（$\mathcal{G}=(V,E)$ 之类），后文不得改记号。

### 3.4 实验矩阵（打勾表，实测频率来自 12 篇方法类）

| 项目 | 地位 | 实测 | 写法要点 |
|---|---|---|---|
| Datasets | **必备** | 12/12 | ≥2 个真实数据集；给统计表（#items/#users/#interactions/时间跨度） |
| Baselines | **必备** | 12/12 | 分代际列（traditional → deep → SOTA），数量 8–25；每条一句话说明代表什么路线 |
| Evaluation metrics | **必备** | 12/12 | 给公式或权威出处 |
| Overall performance | **必备** | 12/12 | 主表加粗最优、下划线次优；正文用相对提升百分比叙述 |
| Ablation study | **必备** | 6/12（方法类里近乎强制） | 逐模块去除，回扣 §4 的模块划分 |
| Parameter sensitivity | 强烈建议 | 5/12 | 2–4 个关键超参的折线图 |
| Efficiency / complexity | 强烈建议 | 8/12 | 训练/推理时间、参数量、显卡型号 |
| Case study / qualitative | 加分 | 4/12 | 给 1–2 个真实样例，展示模型"看见了什么" |
| Significance test | 加分 | 3/12 | paired t-test / Wilcoxon，报 p 值 |
| Cross-dataset / generalization | 加分 | — | 迁移到未训练域，最能压住"只在自家数据上好"的质疑 |

**RQ 化是可选的**：实测 3/12 用 `RQ1/RQ2` 组织实验节；用了就要在 §1 末尾先列出 RQ，并在实验节逐条应答。

### 3.5 数据与可复现

- 数据来源写清楚获取方式与时间窗；用公开数据集时给引用与版本。
- 代码链接放在 §5 开头或脚注（实测 7/12）。
- Declarations 段落按 Elsevier 要求齐备：CRediT、Declaration of competing interest、Data availability、
  生成式 AI 使用声明。

---

## 4. 行文手册

### 4.1 标题

实测的三种可用模式（按在 IP&M 出现频率排序）：

1. **`<机制/方法> for <任务>`**
   *Explicit time embedding based cascade attention network for information popularity prediction*
2. **`<专名>: <机制展开> for <任务>`**
   *3SHNet: Boosting image–sentence retrieval via visual semantic-spatial self-highlighting*
3. **`<动词短语的问题陈述>: <方法定位>`**（更偏应用/交叉时用）
   *Diversity-aware strategies for static index pruning*

规则：
- 标题里必须出现**任务名**；方法名可选但强烈建议。
- 避免"A Novel …"、"An Efficient …"这种自评式开头。
- 交叉领域论文把**领域词放进任务名**（例如 `…for entrepreneurial narrative verification`），
  不要把领域词做成副标题的装饰。
- 长度 8–16 词。

### 4.2 摘要（硬限 250 词）

方法类摘要的实测八步式（以 TCAN 一文为骨架抽象，不复制其措辞）：

```
S1  任务重要性：一句话说清这个信息任务为什么是基础问题。
S2  现状与缺口：现有方法忽略/无法建模的具体东西（1–2 个，具体到机制，不要"效果不佳"）。
S3  提出：In this paper, we propose <全称> (<缩写>), a <方法类型> for <任务>。
S4  机制：<缩写> 通过 A、B、C 三个部件分别解决 S2 的缺口。
S5  数据：在 N 个真实数据集（点名）上验证。
S6  结果：给**具体数值**（指标值 + 相对提升百分比）。
S7  附加证据：消融/效率/泛化各一句。
S8  含义：对信息系统或应用域的一句话含义。
```

**摘要必须带数字。** 这是方法类与实证类最大的写法差别：IP&M 方法类摘要普遍给出 metric 值和相对提升幅度。
关键词 1–7 个，英文，避免带 and/of 的词组。

### 4.3 Highlights

单独文件上传，3–5 条，每条 ≤85 字符（含空格）。写法：一条一个卖点，按
"新方法 / 新机制 / 新数据或新设定 / 主结果 / 含义" 各占一条。

### 4.4 Introduction 的 move map（实测七步）

```
P1  领域与信息任务的重要性（用信息科学的语汇：information overload / filtering / retrieval / governance）
P2  已有工作的两条主线是什么（各 1–2 句，带代表引用）
P3  这些主线共同依赖的前提在真实场景里不成立（转折段，"However, …"）
P4  把缺口拆成编号 challenge：1) … 2) … 3) …（实测常见 2–3 条）
P5  "To address the above challenges, we propose <专名>"，一段话讲清方法直觉
P6  方法部件与 challenge 的对应（一句一部件）
P7  贡献 bullet：3–4 条，最后一条固定是"extensive experiments on N datasets against M baselines"
```

贡献 bullet 的实测句式：`Our main contributions are summarized as follows:` / `Our study introduces several
significant advancements in …:`；每条以名词短语开头（`General explicit time embedding approach.`），
再跟 1–2 句展开。

**交叉领域论文在 P1 与 P7 之间额外承担一件事**：说明这个领域的数据/任务为什么对方法提出了新要求——
否则读者会认为"换个数据集跑一遍"。

### 4.5 Related Work

- 2–4 个子节，按**技术路线**分，不按时间分。
- 每个子节收尾一句点明"这一路线与本文的差别"，不要攒到最后统一比较。
- 长度中位 1,157 词，比 CS 会议长，但不是综述：不要展开到分类学。

### 4.6 Preliminaries

可选（实测 2/9 单列）。若方法涉及图、序列、概率建模，单列一节给定义、问题陈述与记号表；
`Problem statement` 用一句形式化定义：给定 X，学习 f 使得 …。

### 4.7 Method

- 开头一段总述 + 总览图（Fig. 1），并在图注里写清数据流方向。
- 子节顺序 = 数据流顺序（输入编码 → 核心机制 → 融合 → 输出/目标函数 → 复杂度）。
- 每个公式都要有一句"这个式子在做什么"的解释句；公式连排超过三条必须插解释。
- 时态：描述模型用一般现在时（"TCAN encodes …"）。

### 4.8 Experiments

- 开头 1 段说明实验目的（或列 RQ），再给数据集统计表。
- 结果叙述句式：先陈述现象 → 再给数字 → 再解释原因。
  例：`<模型> consistently outperforms the strongest baseline, improving MRR@20 by 4.7%; the gain is largest
  on the sparse dataset, which supports our claim that <机制> compensates for missing context.`
- 每张表/图在正文都要被解释，不能只放不谈。
- 负面或不显著的结果照写并给解释——这是 IP&M 审稿人明确会检查的诚实度信号。

### 4.9 Implications（IP&M 的分水岭）

独立成节（或作为 Discussion 的两个子节），150–1,000 词，两段式：

- **Theoretical implications**：这项工作改变了对该信息问题的什么认识？把结论抬到任务层面，
  而不是重复"我们的模型更好"。
- **Practical implications**：谁能用、在什么系统里用、需要什么条件、会带来什么风险。
  交叉领域论文在这里把领域读者接住（平台运营者、教练、投资人、监管者）。

### 4.10 Conclusion + Limitations

- Conclusion 短（250–650 词）：复述任务、方法、主结果各一句，然后 future work。
- **Limitations 必写**（实测 11/12 出现 limitation 字样）：数据覆盖、泛化边界、计算成本、伦理与隐私。

### 4.11 语言细则

- 人称：`we` 可用且常用；避免 `I`。
- 时态：方法一般现在时；实验过程一般过去时；结论一般现在时。
- 缩写首次展开，摘要与正文各展开一次。
- 数字：小数点后 3–4 位保持全表一致；相对提升写百分比。
- 参考文献 APA author–year；章节编号 1 / 1.1 / 1.1.1。
- 章节标题用名词短语，不用句子。

---

## 5. 设计理念（五条）与常见拒稿形态

### 五条价值判断

1. **任务优先于模型**：IP&M 关心"这个信息任务被推进了"，不关心"这个架构更花哨"。
   选题时先确定任务与指标，再挑机制。
2. **增益必须可验证**：任何"更好"都要有对照、有消融、有数字；没有 baseline 的主张等于没有主张。
3. **机制要可迁移**：审稿人会问"换个域还成立吗"——设计时就留一个跨域或跨数据集实验。
4. **含义闭环**：方法的终点是信息系统的设计决策，不是 leaderboard。
5. **诚实优于漂亮**：写出失败案例、边界与成本，比把所有数字堆成最优更能过审。

### 六种常见拒稿形态（自查用）

1. 纯算法改进 + 公开 benchmark 提升，没有信息任务语境 → desk reject 风险最高。
2. 领域数据 + 现成模型直接跑，方法无新意 → "application without methodological contribution"。
3. baseline 陈旧（只对比三年前方法）或数量太少。
4. 没有消融，读者无法判断增益来自哪个部件。
5. 只有精度，没有效率/复杂度/可扩展性讨论。
6. 没有 implications，结尾停在"我们的模型最好"。
7. **引文停在三年前、零本刊引用** → 编辑在送审前就判定"没跟上这个方向"（§2.4 B1–B3）。
8. **排行榜第二名是自家消融体** → 表面有对照，实际无外部对手（§2.4 B4）。

---

## 6. 交叉领域（domain × method）的四种耦合方式

给定一个领域题目（创业、体育训练、医疗、教育……），把它做成 IP&M 方法论文有四条标准路径。
**选一条，写清楚耦合点，不要四条都沾。**

| 路径 | 方法贡献长什么样 | 适用信号 |
|---|---|---|
| **A. 新任务 + 首个方法** | 把领域痛点形式化为一个此前没有被定义的信息任务，给出任务定义、评测协议、首个基线体系 | 领域里存在"人工做、做不过来"的判断工作 |
| **B. 领域约束驱动的机制创新** | 通用模型在该领域会失效（长尾、稀疏、时序漂移、可核验性要求），据此设计新模块 | 能说清"通用方法在这里为什么失效" |
| **C. 多源异构信息融合** | 领域天然有多模态/多源信号（文本+行为+传感器），贡献在融合与对齐机制 | 数据形态本身就异构 |
| **D. 可信/可核验层** | 在生成或推荐之上加约束层：证据绑定、可核验性打分、安全边界，并给出对应指标 | 领域后果严重（健康、金融、训练安全） |

写作上，交叉论文比纯 CS 论文多两个义务：
1. §1 要交代**领域数据为方法带来的新要求**（不是"我们在新领域上试了试"）。
2. §6 Implications 要写给领域读者，而不只是写给方法读者。

---

## 7. RH 集成

### 7.1 默认路由规则（写进 RH 决策）

```
if target_venue ∈ {IP&M, 及其同型信息科学期刊} and 研究问题可形式化为「输入→输出→可度量正确性」:
        default paper_type = method_core          # 计算模型/方法为主贡献
        domain 内容 → 任务定义 + 数据来源 + implications
        必备件 = {命名方法, ≥2 真实数据集, ≥8 baselines, 消融, 复杂度/效率, implications 节}
else:
        才考虑 empirical / behavioral 设计
```

### 7.2 已落地的 RH 资产

- exemplar 主题：一个专门的 exemplar topic（下文 `<topic-id>`），12 篇 IP&M 方法类 OA 全文入池并挂 PDF，
  其中 8 篇带摘要，可直接作为 prose FORM 的证据来源（`skeleton` / `intro_arc` 若要吃到真实章节树，
  需要先 `rh paper annotate <id>` 生成 paperindex 结构，单篇耗时数分钟）。
- EAG packs：在该主题上按 `abstract` / `style` / `intro_arc` / `skeleton` 四个 unit_type 各 curate 一次
  （首次 curate 需要显式 `paper_ids` 覆盖，否则 RH 会按 venue family 回退到 CCF-A 池，取不到 IP&M 样本），
  之后写作用 `--reuse-pack` 复用。
- 领域侧主题：`ipm-entrepreneurship-informational`（104）、`ipm-sports-training-informational`（105），
  其 `exemplar_pack_abstract` 已由 8 篇 IP&M 真实摘要建成（artifact #5708 / #5709）。
- 领域侧主题：`ipm-entrepreneurship-informational`（104）、`ipm-sports-training-informational`（105）。

### 7.3 命令

```bash
# 复用本手册对应的 IP&M 方法类 FORM
rh exemplar plan     --topic <topic-id> --unit-type skeleton --reuse-pack --target "<本文内容一段话>"
rh exemplar generate --topic <topic-id> --unit-type abstract --reuse-pack --backend self --target "<...>"

# 扩充证据（新一年的 IP&M 方法类 OA 全文）
#   OpenAlex filter: primary_location.source.issn:0306-4573, is_oa:true, publication_year:>YYYY
```

### 7.4 交付前自检清单

- [ ] 标题含任务名，8–16 词，无自评词
- [ ] 摘要 ≤250 词，含方法专名、数据集数量、**具体数值与相对提升**
- [ ] Highlights 3–5 条，每条 ≤85 字符
- [ ] §1 有编号 challenge，并与方法模块一一对应
- [ ] §1 末尾有 3–4 条贡献 bullet，最后一条是实验规模
- [ ] Related work 按技术路线分节，每节收尾点差异
- [ ] 方法有专名、总览图、复杂度分析
- [ ] 实验：≥2 数据集、≥8 baselines、消融、参数敏感性或效率分析
- [ ] **主表第二名是外部方法，不是自家消融体**（§2.4 B4）
- [ ] **至少一条当下技术族（LLM）对照，且不止"我们也试了"**（§2.4 B4）
- [ ] 有 Implications 节（理论 + 实践两段）
- [ ] 有 Limitations
- [ ] 参考文献 40+ 条，APA author–year
- [ ] **当年 ≥3 条、近两年 ≥15%、近三年 ≥30%、本刊 ≥5 条**（§2.4 B1–B3）
- [ ] Declarations 齐备（CRediT / competing interest / data availability / 生成式 AI 声明）
- [ ] 三作者两单位署名占位、第三作者通讯（RH 全局规则）

---

## 附录 A：12 篇 IP&M 方法类论文的逐节解剖

| DOI 尾号 | 年 | 页 | 正文词数 | 图 | 表 | 式 | 顶层章节序列 |
|---|---|---|---|---|---|---|---|
| 103137 | 2022 | 40 | 8,434 | 6 | 5 | 22 | Intro / Related / **The Model** / Experiments / Conclusion |
| 103058 | 2022 | 26 | — | 6 | 8 | 11 | Intro / Related / Lexicons / **Hybrid Model** / Explanation / **Implications, Limits and Challenges** / Conclusion |
| 103278 | 2023 | 24 | 11,908 | 9 | 4 | 17 | Intro / Related / Preliminaries / **TCAN** / Experiment Evaluation / Conclusion |
| 103450 | 2023 | 24 | 12,432 | 4 | 11 | 36 | Intro / Related / **Methodology** / Experimental Evaluations / Discussion / Conclusion |
| 103574 | 2023 | 48 | — | 11 | 10 | 10 | Intro / Related / **Methodology** / Results / Discussion(**Implications**+Limitations) / Conclusion |
| 103716 | 2024 | 20 | 9,721 | 9 | 8 | 12 | Intro / Related / **Approach** / Experiments / **Theoretical and Practical Implications** / Conclusion |
| 103795 | 2024 | 22 | 13,801 | 5 | 14 | 3 | Intro(含 RQ 子节) / Background / **Pruning approaches** / Experimental setup / Experimental results / Conclusions |
| 103873 | 2024 | 16 | 6,577 | 6 | 8 | 4 | Intro / Related / **Methodology** / Experiment / Analysis / Conclusion |
| 103895 | 2024 | 22 | 9,192 | 10 | 6 | 27 | Intro(5 子节) / Related / **Methodology**(5 模块) / Experimental Evaluations / **Implications** / Conclusion |
| 104196 | 2025 | 48 | 19,044 | 14 | 12 | 37 | Intro / Related / Research objective / **Coase** / Experiments(9 子节) / Discussion(**理论+实践含义**+Limitation) |
| 104702 | 2026 | 27 | 11,971 | 8 | 10 | 15 | Intro / Related / Preliminary / **Methodology** / Experiments / Conclusion |
| 102853 | 2022 | 85 | — | 11 | 7 | 16 | （survey 对照组）Intro / Literature search / Preliminaries / SOTA / Discussions / Perspectives / Conclusion |

实验节子节的实测词表（可直接照抄结构，不要照抄措辞）：
`Datasets` · `Baselines` · `Evaluation metrics` · `Parameter/Experimental settings` · `Overall performance /
Comparison with baselines` · `Ablation study` · `Parameter sensitivity analysis` · `Model efficiency /
Inference speed` · `Impact of <某因素>` · `Generalization / Cross-dataset adaptation` · `Visualization /
Interpretability / Qualitative analysis` · `Case study`。

---

## 附录 B：可直接开工的骨架模板

```latex
\section{Introduction}                        % 1,100–1,300 w，含 challenge 编号与贡献 bullet
\section{Related work}                        % 2–4 个技术路线子节，~1,200 w
  \subsection{<路线一>} \subsection{<路线二>}
\section{Preliminaries}                       % 可选，定义 + 问题陈述 + 记号，~500 w
\section{<方法专名>}                           % ~2,500 w
  \subsection{Overview}                       % 配 Fig.1 总览图
  \subsection{<模块 1：对应 challenge 1>}
  \subsection{<模块 2：对应 challenge 2>}
  \subsection{<融合 / 预测层与目标函数>}
  \subsection{Complexity analysis}
\section{Experiments}                         % ~4,000 w，全文最大节
  \subsection{Datasets} \subsection{Baselines} \subsection{Evaluation metrics}
  \subsection{Implementation settings} \subsection{Overall performance}
  \subsection{Ablation study} \subsection{Parameter sensitivity}
  \subsection{Efficiency analysis} \subsection{Case study}
\section{Implications}                        % 理论 + 实践，~300 w
\section{Conclusion and future work}          % ~400 w，含 limitations
```

---

## 附录 C：维护协议

- 每年更新一次证据快照：重跑 §1 的 OpenAlex 口径与 OA 全文解剖，替换 §3.2/§3.4 的实测数字。
- 新增证据只允许来自 IP&M 已发表文章或官方投稿要求；网络二手总结不得直接写入实测表。
- 本手册与 `rh-exemplar-writing`（FORM 迁移）配套：手册给判据与预算，EAG packs 给可执行的 FORM。
