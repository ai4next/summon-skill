# 人格名册规范（Roster Format）

> 已铸人格的索引：存在哪、怎么命名、有哪些字段、怎么检测漂移与冲突、三条回路怎么走。
>
> **上位公理：`design-philosophy.md` 公理 2 与公理 5。**
> 本文件是「产物落盘与生命周期」的 canonical source。
> **质检四轴（生成力 / 自洽性 / 辨识度 / 溯源）的分值、门槛与红线在 `fidelity-scorecard.md`**——
> 本文件只引用，不重定义。

## 一、落盘位置

人格是**用户级 skill**，落在用户目录，不进任何 skill 仓库：

```
~/.claude/skills/<slug>-persona/
├── SKILL.md                     # 人格本体（出厂快照：frontmatter + 六件套）
├── FIDELITY.md                  # 质检四轴评分（出厂快照，重跑会覆盖）
├── REFINE.md                    # 对抗精炼补丁清单（出厂快照，lite 模式无此文件）
├── CALIBRATION.md               # 运行侧校准（运行记录，可增可撤）——见 calibration.md
├── EVALS.jsonl                  # 质检历史（运行记录，追加式，不被覆盖）——见 §5.3
├── FEEDBACK.jsonl               # 使用反馈（运行记录，追加式）——见 §5.2
└── references/
    ├── AXIOMS.md                # 🔴 ground truth（公理集）——目录自包含的关键
    └── …                        # 其余可选：调研底稿、表达速查、案例库
```

> **人格目录是自包含、可迁移的。** `references/AXIOMS.md`（公理集）就在目录里——
> 整个目录拷走，ground truth 跟着走，换台机器仍能检测漂移。
> 这正是它放在**人格目录自己的** `references/` 下、而不是放在别处的理由。

**为什么放用户级而不是项目级**：放 `~/.claude/skills/` 后 harness 能**立即触发**——
铸完就能用，不需要重启会话或改配置。项目级 skill 只在特定仓库生效，
人格是跨项目复用的资产，放错层等于每次都要重铸。

### 源材料：无格式要求（可选约定）

**输入是通用的**（上位原则：`design-philosophy.md` §零）——用户给什么就读什么。
**没有「材料必须长什么样」这回事。**

**可选约定**：只有当你希望 `roster.py` 能自动检测「材料变了 → 该重铸了」时，
才需要给一份**稳定的本地文件**：

```
<source-dir>/<slug>/              # 默认 <source-dir> = ./material
├── MATERIAL.md                   # 脚本**优先识别**的 ground truth 文件名（不是要求）
├── manifest.json                 # 可选：{"material_sha256": "…", "version": N}
└── QUALITY.md                    # 可选：素材质量等级
```

- 脚本找 ground truth 的顺序：`MATERIAL.md` → 目录里**唯一**的 `.md` → `source_material` 本身就是一条路径
- **找不到不算错**——只是漂移检测报 `none`（见 §五）
- `MATERIAL.md` 的 frontmatter **每一项都可选**；`gaps` / `structural_silence` 由 summon 在 P2 自己记
- `QUALITY.md` 只在**存在时**才参与前置门槛（< B 先补材料）；**没有它不等于材料不合格**
  （材料要求见 `persona-forge.md`）

### 产物归属与「只读不写」

**本 skill 的产物只有一个人格目录**（就是上面那棵目录树）。源材料是**输入**，归用户，不属于本 skill 的产物：

| 对象 | 路径 | 归属 | 谁能写 |
|------|------|------|--------|
| **人格目录（唯一产物）** | `~/.claude/skills/<slug>-persona/`（含 `references/AXIOMS.md`） | summon | **只有 summon** |
| **源材料**（不是产物） | 用户给什么就是什么——粘贴文本 / 任意文件 / 任意目录；可选约定见上一节 | 用户 | **只有用户**；summon 只读 |

> 人格铸好、装进 `~/.claude/skills/`、被 harness 触发 → **本 skill 的任务完成**。
> 人格怎么被用、和谁一起用，不是它的事。

**人格 skill 绝不修改源材料目录下的任何文件。材料归用户管，人格归 summon 管。**

## 二、命名规范

| | 命名 | 例 |
|---|------|-----|
| **人格运行体（本 skill 产物）** | `<slug>-persona` | `munger-persona`、`skeptic-cfo-persona` |
| **立场公理集（ground truth）** | `references/AXIOMS.md`（放在人格目录自己的 `references/` 下） | `<slug>-persona/references/AXIOMS.md` |

**后缀固定为 `-persona`**，`roster.py` 只扫这个后缀（**命名空间隔离**）：

- 名册只收录本 skill 的产物，不误扫用户目录下的其他 skill（`~/.claude/skills/` 是共用目录）
- **一个人格一个目录，目录名与 frontmatter 的 `name` 必须一致**——不一致则拒绝收录
- 同一份材料可以铸多次，但产物**目录名必须不同**（如 `munger-persona` 与 `munger-2026q3-persona`）

`<slug>` 用小写字母、数字、连字符（`^[a-z0-9]+(-[a-z0-9]+)*$`），与源材料目录名一致——
规则由本仓库定义，见 `roster-format.md` §二。

## 三、名册（Roster）

**名册是生成物，不是手写文件。** 不要手工维护一份索引——手工索引一定会和磁盘上的实际人格脱节。

`scripts/roster.py` 的职责：

| 步骤 | 动作 |
|------|------|
| 1 | 扫描 `~/.claude/skills/*-persona/SKILL.md` |
| 2 | 解析 frontmatter，抽出名册字段（见 §四），**校验 `name` 与目录名一致** |
| 3 | 读同目录的 `FIDELITY.md`，抽**四轴分数**（生成力 G / 自洽性 C / 辨识度 D / 溯源 S）、总分/等级与 `mode`；再并入 frontmatter `axes` 缓存（轴分以 `FIDELITY.md` 为准） |
| 4 | 重算 ground truth 的 sha256，与 `source_material_sha256` / `source_axioms_sha256` 比对（漂移检测） |
| 5 | 两两比对 `triggers`，标记**完全相同**与**子串包含**两类重叠（冲突检测） |
| 6 | 按 §四 的规则推导**有效状态**（总分 <B 或总分缺失 → 报 `draft`），报告降级与分轴红线旗 |
| 7 | 统计 `FEEDBACK.jsonl`（分三类）与 `CALIBRATION.md` 的生效中条数 |
| 8 | 打印名册表与全部告警 |

**只读脚本**：`roster.py` **只读不写**——它不修改任何文件，**也不生成 `ROSTER.md`**。
检测到漂移或冲突时**报告**，不自动改人格、不自动重铸。

> ⚠️ **本文件 §七 的输出示例是「终端打印」，不是「写入了某个文件」。**
> 早期版本此处误写为「名册已写入 `~/.claude/skills/ROSTER.md`」，与只读契约矛盾，已删除。
> `scripts/selfcheck.py` 会机械检查「任何文档都不得声称 `roster.py` 会写文件」。

## 四、名册字段

字段写在人格 `SKILL.md` 的 frontmatter 里，`roster.py` 直接解析（YAML 子集，见 `scripts/_yaml_subset.py`）：

```yaml
---
schema_version: 2
name: munger-persona
description: |
  查理·芒格的思维框架与表达方式。基于源材料 material/munger 铸造，
  提炼 5 个心智模型、8 条决策启发式和完整表达DNA。
  当用户提到「用芒格的视角」「芒格会怎么看」「munger persona」时使用。
persona_type: real                          # real 实录型 | fictional 原作型 | archetype 合成型
source_material: munger                   # 来源材料 slug（实录型 / 原作型）
source_material_sha256: 3a71…             # 铸造时的材料哈希（漂移依据）
source_material_version: 3                # 铸造时的材料版本
source_axioms: null                         # 合成型：公理集路径（相对人格目录）
source_axioms_sha256: null                  # 合成型：公理集哈希（漂移依据）
axes: {生成力: 24, 自洽性: 20, 辨识度: 15, 溯源: 21,
       total: 80, grade: B, mode: full, date: 2026-09-22}
updated: 2026-09-22
triggers: [用芒格的视角, 芒格会怎么看, munger persona, 逆向思考一下]
status: active                              # active | stale | draft | retired
---
```

**合成型**（这个人不存在）把 ground truth 换成公理集——三型共用同一条路径，只是根不同：

```yaml
persona_type: archetype
source_material: null
source_material_sha256: null
source_material_version: null
source_axioms: references/AXIOMS.md         # 相对**人格目录**的路径
source_axioms_sha256: 4baf…                 # 公理集哈希（合成型的漂移依据）
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | ✅ | 产物契约版本，当前 `2`；`1` 会被接受但报警 |
| `name` | ✅ | 必须是 `<slug>-persona`，且**与目录名一致** |
| `persona_type` | ✅ | `real` 实录型 / `fictional` 原作型 / `archetype` 合成型，决定免责写法（`persona-forge.md`） |
| `source_material` | ✅¹ | **来源描述（自由文本）**：slug、路径、书名、口述日期都行。**输入没有格式要求**（`design-philosophy.md` §零） |
| `source_material_sha256` | ⬜¹ | **可选**：有稳定本地文件时由 `forge_scaffold.py` 写入，作为漂移依据。**没有不算缺陷** |
| `source_material_version` | ⬜¹ | **可选**：材料的 `version`，仅用于人读比对 |
| `source_axioms` | ✅² | 公理集的**路径，相对人格目录**（惯例 `references/AXIOMS.md`）——`roster.py` 会先按此路径找，找不到时兜底认人格目录下的 `references/AXIOMS.md` |
| `source_axioms_sha256` | ✅² | 公理集哈希；**合成型的漂移检测依据** |
| `axes` | ✅ | 内联映射：**四轴分数**（`生成力` /30 · `自洽性` /25 · `辨识度` /20 · `溯源` /25）+ `total` + `grade` + `mode` + `date`。来源是 `FIDELITY.md`；旧字段 `fidelity` / `generativity` 已废弃——`roster.py` 见到 `fidelity` 会告警「请改为 `axes`（四轴）」 |
| `updated` | ✅ | 人格最后修改日期 `YYYY-MM-DD` |
| `triggers` | ✅ | 触发词列表，**冲突检测依据**。只放独有锚点，不放占位符与通用词 |
| `status` | ✅ | `active` / `stale` / `draft` / `retired` |

¹ 实录型 / 原作型；² 合成型。**来源二选一**：给 `source_material`，或给 `source_axioms` + `source_axioms_sha256`。

**必填共七项**：`name` · `persona_type` · `axes` · `updated` · `triggers` · `status`
+ `source_material`（实录 / 原作）**或** `source_axioms` + `source_axioms_sha256`（合成）。

> **`source_material_sha256` 与 `source_material_version` 是可选的。**
> 输入是通用的——材料可以只是一段粘贴的文本，**不在磁盘上留文件也不算缺陷**；
> 代价只是这个人格的漂移检测报 `none`（无法检测），`roster.py` 会给一条提示性告警。

**`status` 的判定规则**（不靠人拍脑袋）：

| 条件 | 有效状态 |
|------|---------|
| `total` ≥70（B）且四轴均未触红线，且哈希一致 | `active` |
| `total` <70，或**任一轴触红线**（溯源 S = 0 / 自洽性 C <15 / 辨识度 D <12） | `draft` |
| 哈希不一致（材料 / 公理集变过） | `stale` |
| ground truth 已不存在（材料被删 / 公理集丢失） | `stale` |
| 用户显式弃用 | `retired` |

> 分轴红线与门槛的 canonical source 是 `fidelity-scorecard.md` §五；本表只引用。
> **生成力 G <12 不降级**——产物是「复读机」，可交付但**不得声称能提供新视角**。

> **`roster.py` 只报告有效状态，不改文件。** 它按**总分**与**哈希**推导有效状态
> （`active` 但总分 <B 或总分缺失 → 报 `draft`），并在「四轴明细」里逐条标出分轴红线旗
> （`❌ 溯源 S=0 → 判 D` / `⚠️ 自洽性 C<15` / `⚠️ 辨识度 D<12` / `⚠️ 生成力 G<12（复读机）`）——
> **修正 frontmatter 是人的动作**。
>
> ⚠️ 分轴红线**目前只标旗、不自动改「状态」列**。读到 `active` 但带红线旗的条目，
> 按红线判定处置（canonical source：`fidelity-scorecard.md` §五）。
> 红线与门槛的 canonical source 是评分卡；本表只引用。

## 五、漂移检测

**问题**：人格是某一时刻从 ground truth 铸出来的快照。ground truth 会变
（材料 `version` +1、`gaps` 增删、公理集修订），人格却停在原地——
**根已经变了，人格还在用旧认知说话**。

**机制**：`source_material_sha256`（或 `source_axioms_sha256`）记录铸造时的内容哈希。
`roster.py` 每次运行**重算当前哈希**并比对：

| 比对结果 | 判定 | 建议 |
|---------|------|------|
| 一致 | 人格与根同步 | 无需动作 |
| 不一致 | **人格已陈旧（stale）** | 提示「ground truth 已更新，建议重铸」 |
| 根不在本地 | `stale`（无法验证 ≠ 已验证） | 提示把材料放回 / 恢复公理集 |

**ground truth 按材料类型取**（与 `fidelity-scorecard.md` §四 一致）：

| 材料类型 | ground truth | 漂移依据 |
|---------|-------------|---------|
| **实录型** `real` | 用户提供的材料（档案 / 文献 / 公开言论） | `source_material_sha256` |
| **原作型** `fictional` | 原作设定资料 | `source_material_sha256` |
| **合成型** `archetype`（这个人不存在） | 公理集 `references/AXIOMS.md`（**在人格目录里**） | `source_axioms_sha256` |

> **合成型不是「材料不足的降级」，是三条平等主路径之一。** 它没有保真包袱，
> 但根由用户提供的信息当场立定——所以它同样**有** ground truth，也同样会漂移。

**重铸前先看差异**，不是所有变更都需要重铸：

| 变更 | 是否需重铸 |
|------|-----------|
| 新增素材但骨架未变 | 否，可只更新「调研信息源」段 |
| `gaps` 增删 / 结构性沉默增删 | **是**，诚实边界必须跟着变 |
| 核心骨架条目增删 | **是**，心智模型要重取 |
| `confidence` 中 D 级占比变化 >10% | **是**，诚实边界措辞要调整 |
| 公理集增删一条 | **是**，闭包变了 |
| 仅错别字/格式修订 | 否，重算哈希后刷新 `source_*_sha256` 即可 |

**关键**：ground truth 是**只读**的。重铸 = 从当前 ground truth 重新铸一份人格，覆盖旧人格目录；
**不是**去改材料来迁就人格。

### 5.1 三条回路（速度不同，别混）

```
① 运行侧（快，即时）
   使用中失败 ─→ CALIBRATION.md ─→ 下次触发即生效
                 （只许收窄，见 calibration.md）

② 材料侧（慢，需人工）
   使用中失败 ─→ FEEDBACK.jsonl ─→【人工】用户修订源材料 / 修订公理集
                ─→ version++ / 公理集改 ─→ ground truth 内容变 ─→ 哈希变
                ─→ roster.py 报 stale ─→ 重铸 ─→ 新四轴记入 EVALS.jsonl

③ 规则侧（更慢，改 skill 自己）
   公理未覆盖的情形 ─→ FEEDBACK.jsonl（failure: policy_gap）
                ─→ 累积后推动 design-philosophy.md 的公理射程演进
```

**不要以为写了 `FEEDBACK.jsonl` 就会触发漂移检测。不会。**
`roster.py` 只哈希 ground truth 文件。往人格目录追加 `FEEDBACK.jsonl` **不改变那个哈希**，
所以漂移检测**不会**因此报错。

**触发点是人的动作（用户改材料 / 修订公理集 / 重铸），不是 summon 的写入。**
这条链需要一次人工介入，**不存在全自动闭环**——如实描述，不要假装是自动的。

## 5.2 FEEDBACK.jsonl（人格使用反馈 · 出口）

**位置**：`~/.claude/skills/<slug>-persona/FEEDBACK.jsonl` —— **在 summon 自己的地盘**。

**归属原则**：材料归用户管，人格归 summon 管，**任何一方都不写对方的地盘**。
用户只读本文件，summon 只写本文件。

```json
{"schema_version":1,"date":"2026-09-22","persona":"munger-persona",
 "material_sha256":"3a71…","context":"review",
 "question":"…","failure":"in_scope_gap","evidence":"材料 §决策启发式 第3条",
 "note":"…"}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | ✅ | 当前 `1` |
| `persona` | ✅ | 人格 slug |
| `material_sha256` | ✅ | **使用时** ground truth 的哈希——用于判断这条反馈针对哪一版 |
| `context` | ✅ | 产生该反馈的**情境**：`session`（会话中实测）/ `review`（事后复盘）/ `eval`（评测中）。**v3 起由 `formation` 更名**——多人编排的概念已删除，CLI 同步为 `--context`（默认 `review`） |
| `failure` | ✅ | 失败类型，见下表 |
| `evidence` | ✅ | **证据指针**（公理 / 模型 ID / 材料条目 / 行号）。**无证据指针 → 是意见不是缺陷**（公理 2） |

### 失败类型分三类（关键）

| 类别 | 类型 | 含义 | 计入缺陷汇总？ | 去处 |
|------|------|------|--------------|------|
| **人格缺陷** | `style_drift` | 表达不像（句式/词汇/节奏偏离表达DNA） | ✅ | `CALIBRATION.md`（收窄）+ 出口 |
| | `in_scope_gap` | 问题**在该材料范围内**，却没答好 | ✅ | 同上 |
| | `wrong_stance` | 立场与 ground truth 的 A/B 级条目矛盾（**必须附反证指针**） | ✅ | 同上 |
| | `incoherent` | **模型之间互相打架**：两条主张在同一情境下给出相反判断，且都没提对方 | ✅ | 同上 |
| **忠实沉默** | `faithful_silence` | 材料已标注该缺口 / 主体主动不公开 → **拒答是正确行为** | ❌ **不计入** | 仅统计频率 |
| **规则缺口** | `policy_gap` | 本 skill 的**规则本身没覆盖**这个情形 | ❌ **不计入** | 推动**公理体系**演进 |

> ⚠️ **`incoherent` 与「内在张力」是两回事。** 判据是**这个人格自己知不知道那个冲突**：
> 知道并说出来 = **张力**（资产，要保留）；不知道、两句并列摆着 = **矛盾**（`incoherent`，要修）。
> 误把张力记成 `incoherent`，会逼着把这个人格的深度删掉（公理 4）。

> ⚠️ **`faithful_silence` 必须排除在缺陷汇总之外。**
> 拒答在本系统里常常是**正确行为**——闭包外、结构性沉默、伦理红线都要求拒答。
> 若把它当缺陷，就会被推着去「补上」这个缺口，从而**为刻意保持沉默的人编造立场**——
> 那正是评分卡判 **0 分**的行为（公理 5）。
> 记录它是为了**统计忠实沉默的频率**，不是为了修它。

> ⚠️ **`policy_gap` 也不是人格缺陷。**
> 它记录的是**本 skill 的规则不完备**（`design-philosophy.md` §三）——
> 出现频次高说明某条公理需要补充射程，**不是某个人格需要重铸**。
> 正确处置是回公理推导，而不是就地编一条新规则。

### 记录时机

- ✅ **会话中实测**（`--context session`）：人格被 harness 触发使用时暴露的失败
- ✅ **事后复盘**（`--context review`）：用户读完回答后判定
- ✅ **评测中**（`--context eval`）：P6 四轴验真暴露的失败（`incoherent`、溯源缺口、表达DNA 空转等）
- ⚠️ **人格正在角色内回答时不要中断去写文件**——那等于跳出角色。
  会话中的失败留到该轮回答结束后、或复盘时补记

## 5.3 EVALS.jsonl（质检历史）

**问题**：`FIDELITY.md` 每次重铸都被覆盖，**分数历史随之销毁**——无法回答「重铸后比上一版好在哪」。

**解法**：追加式记录，只增不改。每行一条独立评测。

```json
{"schema_version":1,"run_id":"2026-09-22T11:00:00Z","version":3,
 "date":"2026-09-22","artifact_sha256":"7c1e…","mode":"full",
 "models":{"answer":"claude-sonnet-5","score":"claude-opus-5"},"scorers":2,
 "questions":[
   {"id":"q1","kind":"known","text":"…","status":"active"},
   {"id":"q4","kind":"out_of_scope","text":"…","status":"retired",
    "retired_reason":"该领域已被材料覆盖，不再是超范围题"}
 ],
 "axes":{"生成力":24,"自洽性":20,"辨识度":15,"溯源":21},
 "notes":"…"}
```

**题目内嵌在记录里，不做全局题库**——人格会变（缺口被补、条目被修正），
全局固定题库会与之脱节。

**关键陷阱**：超范围题（`kind: out_of_scope`）的正确答案是「拒答 + 标注推断」。
当材料补上该领域后，正确答案变成「真答」，而评分规则仍把拒答记为正确 →
**越完整的人格分越低**（虚假退步）。所以：该领域被覆盖后把该题标 `retired`，
`compare` 会提示「本次对比无效」。

**四轴分别记录，分别对比，绝不相加**（公理 3）：

| 轴 | 字段 | 满分 | 测什么 |
|----|------|------|--------|
| **生成力 G** | `axes.生成力` | 30 | 能否在闭包内推出公理集没写过的判断 |
| **自洽性 C** | `axes.自洽性` | 25 | 模型之间立不立得住（矛盾 = 缺陷，张力 = 资产） |
| **辨识度 D** | `axes.辨识度` | 20 | 去掉署名，认不认得出是谁 |
| **溯源 S** | `axes.溯源` | 25 | 每条主张能否指回公理 / 材料；0 分 → **直接判 D** |

> `total` / `grade` 只是**索引用的汇总**（`FIDELITY.md` 里的总分与等级），
> **不得**用它替代逐轴报告，更不得让四个数互相补偿（公理 3）。
> 红线与门槛见 `fidelity-scorecard.md` §五。

**追加纪律**：只追加，不改历史行；每条必须带 `models`（`answer` 与 `score` 两个模型）、
`scorers`、**非空 `questions`**、**四轴齐全**。缺任一 → 拒绝写入。
`scorers < 2` 或题目集变动或四轴不齐 → `compare` **拒绝给趋势结论**，如实说明原因。

**lite 模式仍跑 P6（四轴都测）**，只是跳过 P7、无 `REFINE.md`——
它意味着「编造」与「矛盾」两个失败模式**没有被对抗过**，交付时必须标 `mode: lite`，
**不得把 lite 的产物说成 full 的产物**。

## 5.4 CALIBRATION.md（运行侧校准 · 本地回路）

**位置**：`~/.claude/skills/<slug>-persona/CALIBRATION.md`

运行侧问题的即时回路：**只许收窄，不许放宽**。它不改 ground truth 哈希，
所以**不触发漂移检测**；它也不改四轴分数。

完整规范（格式、收窄测试、生命周期、防滥用）见 **`calibration.md`**——本文件不重复。

`roster.py` 会报告它的「生效中」条数：**> 10 条说明根因在材料或人格本身，该重铸了**。

## 六、冲突检测

`roster.py` 每次运行检查三类冲突：

### 1. 触发词重叠

两两人格比对 `triggers`，两类都报：

| 重叠类型 | 例 | 处理 |
|---------|----|------|
| **完全相同** | 「逆向思考一下」同时属于 A 与 B | **必须消解**：改其中一个人格，或从两者中都删掉 |
| **子串包含** | 「芒格」⊂「用芒格的视角」 | **保留长词，删短词**——短词会误触发 |

```
⚠ 触发词冲突：「逆向思考一下」同时属于 munger-persona 与 skeptic-cfo-persona
⚠ 触发词包含：「芒格」是「用芒格的视角」的子串（munger-persona 内部自包含，或跨人格）
```

**原则**：触发词必须是**这个人格独有**的锚点。两个人格抢同一个触发词，
等于两个 skill 抢同一个用户意图——harness 只能随机选一个，用户得到的是不确定的行为。
**通用词（「帮我分析一下」）直接从 `triggers` 删除。**

### 2. slug 碰撞

| 情况 | 处理 |
|------|------|
| `~/.claude/skills/<slug>-persona/` 已存在，但来源材料不同 | **报错**，要求改名或先 `retired` 旧人格 |
| `name` 字段与目录名不一致 | **报错**，拒绝收录进名册 |
| 两个人格的 `source_material`（或 `source_axioms`）相同 | **警告**：同一份根铸了两次，确认是否有意为之 |

### 3. 状态冲突

| 情况 | 处理 |
|------|------|
| `status: active` 但 `FIDELITY.md` 缺失或总分 <70 | 报有效状态 `draft` 并告警 |
| `status: active` 但触分轴红线（S = 0 / C <15 / D <12） | 在「四轴明细」标红线旗，并提示按红线处置（canonical source：`fidelity-scorecard.md` §五） |
| `source_material` 指向的 `material/<slug>/` 已不存在 | 报 `stale` |
| 合成型的 `references/AXIOMS.md` 已不存在 | 报 `stale` |
| ground truth 哈希不一致 | 报 `stale` |

## 七、名册输出示例

```
$ python3 scripts/roster.py --skills-dir ~/.claude/skills --source-dir material

人格名册 · 共 4 个 · 扫描自 ~/.claude/skills/*-persona/

| slug | 类型 | 来源档案 | 四轴 | 更新时间 | 触发词 | 状态 |
|------|------|---------|------|---------|--------|------|
| munger-persona | real | munger @3a71f2 (v3) | G24 C20 D15 S21 | 2026-09-22 | 用芒格的视角、芒格会怎么看 | active |
| skeptic-cfo-persona | archetype | 公理集 references/AXIOMS.md @b204e9 | G23 C22 D17 S20 | 2026-09-20 | 怀疑论CFO、帮我审一下这张报表 | active |
| holmes-persona | fictional | holmes-canon @7c1d40 (v2) | G18 C19 D16 S20 | 2026-09-18 | 福尔摩斯模式、用演绎法看看 | active |
| jobs-persona | real | jobs @0e55aa (v1) | G12 C14 D11 S13 | 2026-09-15 | 乔布斯会怎么看 | draft |

四轴明细（生成力 G/30 · 自洽性 C/25 · 辨识度 D/20 · 溯源 S/25）
  **四个数分开报、不相加、不互相补偿**（design-philosophy.md 公理 3）
  munger-persona             总分 80/100 (B) · 生成力 24/30 · 自洽性 20/25 · 辨识度 15/20 · 溯源 21/25 · mode full
  skeptic-cfo-persona        总分 82/100 (B) · 生成力 23/30 · 自洽性 22/25 · 辨识度 17/20 · 溯源 20/25 · mode full
  holmes-persona             总分 73/100 (B) · 生成力 18/30 · 自洽性 19/25 · 辨识度 16/20 · 溯源 20/25 · mode lite
  jobs-persona               总分 50/100 (D) · 生成力 12/30 · 自洽性 14/25 · 辨识度 11/20 · 溯源 13/25 · mode full · ⚠️ 总分 < B · ⚠️ 自洽性 C<15 · ⚠️ 辨识度 D<12

告警与漂移（3 处）
  ⚠️  漂移：jobs-persona 的来源材料 jobs 源材料已更新 —— 人格可能已过时，建议重铸
  ⚠️  触发词冲突「帮我审一下」同时属于 jobs-persona、skeptic-cfo-persona —— 完全相同，必须消解
  ⚠️  jobs-persona: 状态降级: `active` → `draft`（总分 50 < B/70）

运行侧校准（CALIBRATION.md，见 references/calibration.md §五）
  skeptic-cfo-persona        ✅ 存在 · 生效中 3 条 · 已撤销 1 条 · 待观察 1 条

使用反馈（人格缺陷才计入汇总）
  munger-persona             人格缺陷 2 条 · 忠实沉默 1 条 · 规则缺口 0 条
  下一步：由**用户**读这些反馈，决定是否修订源材料。
  注意：反馈文件不改材料哈希，**不会**自动触发上面的漂移检测。

  共 4 个人格 · 总分 ≥B 的 3 个 · 生成力 G ≥12 的 4 个（四轴分开报，不相加）
```

**表列说明**：`来源材料` 列给出源材料 slug、哈希前 6 位与版本（合成型给出公理集路径）——
**哈希前 6 位足够人眼比对**，全哈希只在脚本内部用。
`四轴` 列给 `G`/`C`/`D`/`S` 四个分数；**总分与等级**在紧随其后的「四轴明细」段里给。
**四个数分开报，不相加、不互相补偿**（公理 3）；四轴不齐或未跑质检的人格如实标 `未测`，
**不得声称达标**；`mode lite` 只表示 P7 未跑。

## 八、检查清单

### 落盘与字段
- [ ] 人格在 `~/.claude/skills/<slug>-persona/`，不是项目级、不在 skill 仓库内？
- [ ] 目录**自包含**：`SKILL.md` · `references/AXIOMS.md`（ground truth）· `FIDELITY.md` 都在？
- [ ] 目录名与 frontmatter `name` 一致？目录里有 `SKILL.md` 与 `FIDELITY.md`？
- [ ] 必填字段齐全（七项 + 来源二选一）？`schema_version` 为 2（旧人格为 1 时已记入重铸计划）？
- [ ] `source_material_sha256`（若材料有稳定本地文件）由 `forge_scaffold.py` 自动写入，不是手填的？
- [ ] 若没记哈希，确认这是**有意的通用输入**，而不是漏了？
- [ ] frontmatter 用 `axes` 一项承载**四轴分数 + 总分/等级 + mode + 日期**（不再用 `fidelity` / `generativity`）？
- [ ] `status` 按 §四 的规则推导，不是人拍的？

### 名册与冲突
- [ ] `roster.py` 能完整扫出该人格，无解析错误？
- [ ] 触发词都是该人格独有的锚点，无通用词、无完全相同重叠、无子串包含？
- [ ] 无 slug 碰撞？`retired` 的人格已从主表移出或明确标注？

### 漂移与回路
- [ ] 跑过 `roster.py`，确认无 `stale` 报警（或已知晓并计划重铸）？
- [ ] 重铸是**从当前 ground truth 重铸**，而不是改材料去迁就人格？
- [ ] 合成型的 `references/AXIOMS.md` 在位，且 `source_axioms_sha256` 与它一致？
- [ ] `FEEDBACK.jsonl` 的每条都带 `evidence` 与 `material_sha256`，且 `context` ∈ {`session`, `review`, `eval`}？
- [ ] `faithful_silence` 与 `policy_gap` **都没有**被计入缺陷汇总？`incoherent`（矛盾）与「内在张力」分开了？
- [ ] `CALIBRATION.md` 的生效中条目 ≤10，且每条都带来源？
- [ ] 没有向用户宣称「写反馈会自动触发重铸」？
