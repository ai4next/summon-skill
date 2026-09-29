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
├── CALIBRATION.md               # 运行侧校准（运行记录，可增可撤）——见 §5.4
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

**输入是通用的**——用户给什么就读什么，材料格式不是本 skill 的事
（canonical source：`design-philosophy.md` §零）。本文件只约定**可选的**落盘布局：
只有当你希望 `roster.py` 能自动检测「材料变了 → 该重铸了」时，才需要给一份**稳定的本地文件**：

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

> 「任务何时完成」的判据见 `design-philosophy.md` §零.1——**人格被 harness 触发即完成**。

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

> ⚠️ **§七 的输出示例是「终端打印」，不是「写入了某个文件」**（早期版本曾误写「名册已写入 `~/.claude/skills/ROSTER.md`」，与只读契约矛盾，已删除）。
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

> **`source_material_sha256` / `source_material_version` 是可选的**：材料可以只是一段粘贴的文本，
> **不在磁盘上留文件也不算缺陷**——代价只是漂移检测报 `none`（见 §五），`roster.py` 给一条提示性告警。

**`status` 的判定规则**（不靠人拍脑袋）：

| 条件 | 有效状态 |
|------|---------|
| `total` ≥70（B）且四轴均未触红线，且哈希一致 | `active` |
| `total` <70，或**任一轴触红线**（溯源 S = 0 / 自洽性 C <15 / 辨识度 D <12） | `draft` |
| 哈希不一致（材料 / 公理集变过）→ 漂移状态 `stale` | `stale` |
| ground truth 已不存在（材料被删 / 公理集丢失）→ 漂移状态 `unknown` | `stale`（**「无法验证 ≠ 已验证」**） |
| 用户显式弃用 | `retired` |

> 分轴红线与门槛的 canonical source 是 `fidelity-scorecard.md` §五；本表只引用。
> **生成力 G <12 不降级**——产物是「复读机」，可交付但**不得声称能提供新视角**。

> **`roster.py` 只报告有效状态，不改文件**（只读契约见 §三）。它按**总分**与**哈希**推导有效状态
> （`active` 但总分 <B 或总分缺失 → 报 `draft`），并在「四轴明细」里逐条标出分轴红线旗
> （`❌ 溯源 S=0 → 判 D` / `⚠️ 自洽性 C<15` / `⚠️ 辨识度 D<12` / `⚠️ 生成力 G<12（复读机）`）。
> ⚠️ 红线**目前只标旗、不自动改「状态」列**——读到带旗的 `active` 条目按红线判定处置，
> **修正 frontmatter 是人的动作**。

## 五、漂移检测

**问题**：人格是某一时刻从 ground truth 铸出来的快照。ground truth 会变
（材料 `version` +1、`gaps` 增删、公理集修订），人格却停在原地——
**根已经变了，人格还在用旧认知说话**。

**机制**：`source_material_sha256`（或 `source_axioms_sha256`）记录铸造时的内容哈希。
`roster.py` 每次运行**重算当前哈希**并比对：

| 比对结果 | 漂移状态 | 有效状态 | 建议 |
|---------|---------|---------|------|
| 一致 | `ok` | 不变 | 无需动作 |
| 不一致 | **`stale`**（真漂移） | `stale` | 提示「ground truth 已更新，建议重铸」 |
| **根不在本地**（记过哈希，文件没了） | **`unknown`** | **`stale`** | 提示把材料放回 / 恢复公理集 |
| 从没记过哈希（纯粘贴文本） | `none` | 不变 | 无需动作（**不是缺陷**） |

> **`unknown` 与 `stale` 是两回事，但有效状态都是 `stale`。**
> · **漂移状态**如实反映「我们知道什么」：`unknown` = **无法核对**，**不是**「检测到漂移」——
>   所以终端**不会**为它打印「建议重铸」（那是谎报）。
> · **有效状态**按「**无法验证 ≠ 已验证**」处理：根已找不到的人格不该继续挂在 `active` 上。
>   两条不矛盾：**措辞如实，处置从严。**
>
> 历史教训：代码返回 `unknown`、文档写「报 `stale`」，合起来就是「孤儿人格永远挂在 `active`」——状态名与有效状态必须分成两列写清。

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
                 （只许收窄，见 §5.4）

② 材料侧（慢，需人工）
   使用中失败 ─→ FEEDBACK.jsonl ─→【人工】用户修订源材料 / 修订公理集
                ─→ version++ / 公理集改 ─→ ground truth 内容变 ─→ 哈希变
                ─→ roster.py 报 stale ─→ 重铸 ─→ 新四轴记入 EVALS.jsonl

③ 规则侧（更慢，改 skill 自己）
   公理未覆盖的情形 ─→ FEEDBACK.jsonl（failure: policy_gap）
                ─→ 累积后推动 design-philosophy.md 的公理射程演进
```

**写了 `FEEDBACK.jsonl` 不会触发漂移检测**——`roster.py` 只哈希 ground truth 文件，追加反馈**不改变那个哈希**。
**触发点是人的动作**（用户改材料 / 修订公理集 / 重铸），不是 summon 的写入：这条链需要一次人工介入，**不存在全自动闭环**。

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

> ⚠️ **`faithful_silence` 与 `policy_gap` 都必须排除在缺陷汇总之外。**
> 拒答在本系统里常常是**正确行为**——闭包外、结构性沉默、伦理红线都要求拒答；若把它当缺陷，
> 就会被推着去「补上」这个缺口，从而**为刻意保持沉默的人编造立场**——那正是评分卡判 **0 分**的行为（公理 5）。
> 记录它只为**统计忠实沉默的频率**，不是为了修它。
> `policy_gap` 记录的是**本 skill 的规则不完备**（`design-philosophy.md` §三）：频次高说明某条公理需要补充射程，
> **不是某个人格需要重铸**；正确处置是回公理推导，而不是就地编一条新规则。

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

运行侧问题的即时回路：**唯一的硬约束、收窄测试与理由见下「最重要的约束」**。
它不改 ground truth 哈希，所以**不触发漂移检测**；也不改四轴分数（运行侧收窄，不是重新铸造）。

### 两类问题，两条回路

同一个「回答得不对」，可能是两种完全不同的病：

| | **材料侧**（材料错 / 缺） | **运行侧**（材料对，表现差） |
|---|---|---|
| 例子 | 档案漏了「他 2020 年后改口了」 | 遇到具体标的时忘了拒绝给买卖建议 |
| 谁的错 | 材料 / 公理集 | 人格的运行行为 |
| 去处 | `FEEDBACK.jsonl`（**出口**，给**用户**） | `CALIBRATION.md`（**本地**，给自己） |
| 谁处理 | 用户 | summon |
| 生效 | 重铸后 | **下次触发即生效** |
| 速度 | 慢，需人工介入 | 即时 |

**两类都可能有**：那就两边都写。`CALIBRATION.md` 的每条**必须**引用产生它的 `FEEDBACK.jsonl` 条目
（或至少带同样的 `evidence` 证据指针）——否则它就成了无出处的意见，违反公理 2。

### 最重要的约束：只许收窄，不许放宽

**校准可以缩小这个人格说话的范围，绝不可以扩大。**

| ✅ 允许（收窄） | ❌ 禁止（放宽） |
|---|---|
| 加警告：「这类问题上先说明我的口径只覆盖财务」 | 新增立场：「材料没写，但更完整的是…」 |
| 加拒答触发：「涉及具体标的时不给买卖建议」 | 放宽诚实边界：「其实这个问题我可以答」 |
| 收紧表达DNA：「避免连续使用长句」 | 删除反模式：「这条反模式太严了，去掉」 |
| 修正 Fallback 分支：「工具不可用时先说明再给框架」 | 改任何与 ground truth 相关的字段 |
| 收窄 Protocol 维度：「只在 X 类问题上做研究」 | 扩大研究维度到材料没有的领域 |
| 把并列的**矛盾**收窄为显式**张力**（人格自己承认），或删掉其中一条 | 把人格自己承认的**张力**当矛盾删掉——那是资产（公理 4） |

**收窄测试（唯一判据）**：

> **问一句：「这条校准让这个人在更多问题上说话，还是在更少问题上说话？」**
> **更多 → 越界，驳回。更少 → 合法。**

**为什么只许收窄**：公理 2。放宽必然意味着**断言闭包外的内容**——那是编造，
会把**溯源 S** 打到 0 分并**直接判 D**。
收窄只是减少断言范围，**在数学上不可能越出闭包**，所以永远安全。

> ⚠️ P7 对抗精炼必须把 `CALIBRATION.md` 纳入攻击面（攻击面清单 canonical source：`adversarial-refine.md`）。

### 格式

```markdown
# 运行侧校准

**人格**：<slug>-persona
**ground truth**：references/AXIOMS.md @ sha256 4baf…（合成型：公理集）
　或（实录型 / 原作型）源材料 MATERIAL.md @ sha256 3a71…（version N）
**轮次**：1 ｜ **最后更新**：YYYY-MM-DD

## 生效中

| # | 触发条件 | 校准动作（收窄） | 来源 | 生效日期 |
|---|---------|----------------|------|---------|
| 1 | 被问到具体投资标的的买卖 | 拒绝给操作建议，只谈评估方法 | FEEDBACK 2026-09-22 `in_scope_gap` | 2026-09-23 |
| 2 | 对话超过 20 轮 | 输出前重读表达DNA 的「句式」与「确定性」两行 | FEEDBACK 2026-09-24 `style_drift` | 2026-09-24 |
| 3 | 被问到 X 情境（两条主张在此会给出相反判断） | 只承认「此处我只有未调和的张力，没有统一判断」，不强行二选一 | FEEDBACK 2026-09-24 `incoherent` | 2026-09-24 |

## 已撤销

| # | 原动作 | 撤销日期 | 撤销理由 |
|---|--------|---------|---------|
| — | （示例）回避平台型业务话题 | 2026-09-25 | ground truth v4 已补该维度，根因消失 |

## 待观察

| # | 现象 | 首次出现 | 观察结论 |
|---|------|---------|---------|
| 1 | 被追问时倾向重复上一轮结论 | 2026-09-24 | 暂未定性为缺陷，先观察 |
```

| 字段 | 必填 | 说明 |
|------|------|------|
| 触发条件 | ✅ | 什么情况下生效（要可判定，不能是「感觉不对时」） |
| 校准动作 | ✅ | 具体做什么，且必须是**收窄**动作 |
| 来源 | ✅ | 产生它的 `FEEDBACK.jsonl` 条目（日期 + 失败类型），或同等证据指针。失败类型见 §5.2 |
| 生效日期 | ✅ | `YYYY-MM-DD` |
| 状态 | 由所在小节表达 | 生效中 / 已撤销 / 待观察 |

### 人格激活时怎么读

`CALIBRATION.md` 是 `SKILL.md` 的**运行侧覆盖层**，不是它的替代：

| 文件 | 性质 | 谁改 |
|------|------|------|
| `SKILL.md` | **出厂快照**——冻结，可审计 | 只在重铸时 |
| `CALIBRATION.md` | **运行覆盖**——可增可撤 | 使用中，经用户确认 |

**spawn prompt 的写法**（两个文件属于**同一个人格**：一个是身份，一个是运行侧收窄）：

```
你扮演 [人格名]。只读这个目录下的两个文件：
  ~/.claude/skills/[slug]-persona/SKILL.md
  ~/.claude/skills/[slug]-persona/CALIBRATION.md（若存在；它只收窄行为，不改变身份）
不要读取其他人格的文件，不要猜测别人会怎么回答。
```

**为什么做成覆盖层而不是直接改 `SKILL.md`**：

1. **可审计**——出厂快照保持原样，能回答「这份人格出厂时是什么样」
2. **可撤销**——ground truth 更新后，撤销一条校准不需要重铸
3. **可对抗**——P7 的攻击者能对着一份**独立文件**审「有没有放宽边界」，而不是在 400 行里找改动

### 生命周期

| 事件 | 对 `CALIBRATION.md` 做什么 |
|------|--------------------------|
| 使用中发现失败 | 提出条目 → **用户确认** → 写入「生效中」 |
| 伦理红线类收窄（如加拒答触发） | **可自动生效**，但**必须告知用户** |
| 条目累计 > 10 条 | ⚠️ **停止追加**：说明根因在材料或人格本身，该重铸了 |
| ground truth 更新（哈希变 → `roster.py` 报 `stale`） | **逐条重判**：根因可能已被新版本修复 → 移入「已撤销」 |
| 重铸完成 | 逐条重判；确认仍需要的才保留 |
| 用户要求撤销某条 | 移入「已撤销」并写理由（不删除历史） |

`roster.py` 会报告它的「生效中」条数：**> 10 条说明根因在材料或人格本身，该重铸了**。

### 防滥用

| 风险 | 防线 |
|------|------|
| 变成「悄悄加立场」的后门 | **收窄测试**（见「最重要的约束」）+ P7 认知攻击者审 `CALIBRATION.md` |
| 条目无限膨胀，人格变成补丁堆 | 生效中 > 10 条 → 强制重铸 |
| 无出处的校准 | 每条必须带来源（`FEEDBACK.jsonl` 条目 / 证据指针） |
| 绕过用户裁决 | 除伦理红线类外，条目须用户确认才生效 |
| 校准与 `SKILL.md` 冲突 | **以 `SKILL.md` 的身份与诚实边界为准**；校准只能在其之上**收紧**，不能与之矛盾 |
| 用「消除矛盾」当借口删掉张力 | 判据见 §5.2（`incoherent` = 矛盾；张力是资产）；张力要保留（公理 4） |

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
| `source_material` 指向的 `material/<slug>/` 已不存在 | 漂移 `unknown`，有效状态降为 `stale` |
| 合成型的 `references/AXIOMS.md` 已不存在 | 漂移 `unknown`，有效状态降为 `stale` |
| ground truth 哈希不一致 | 漂移 `stale`，有效状态降为 `stale` |

## 七、名册输出示例

```
人格名册 · 共 4 个 · 扫描自 ~/.claude/skills/*-persona/
| slug | 类型 | 来源档案 | 四轴 | 更新时间 | 触发词 | 状态 |
|------|------|---------|------|---------|--------|------|
| munger-persona | real | munger @3a71f2 (v3) | G24 C20 D15 S21 | 2026-09-22 | 用芒格的视角、芒格会怎么看 | active |
| skeptic-cfo-persona | archetype | 公理集 references/AXIOMS.md @b204e9 | G23 C22 D17 S20 | 2026-09-20 | 怀疑论CFO、帮我审一下这张报表 | active |
| holmes-persona | fictional | holmes-canon @7c1d40 (v2) | G18 C19 D16 S20 | 2026-09-18 | 福尔摩斯模式、用演绎法看看 | active |
| jobs-persona | real | jobs @0e55aa (v1) | G12 C14 D11 S13 | 2026-09-15 | 乔布斯会怎么看 | draft |
四轴明细（G/30 · C/25 · D/20 · S/25；四个数分开报、不相加、不互相补偿）：munger 80/100 (B) G24 C20 D15 S21 full ｜ skeptic-cfo 82/100 (B) G23 C22 D17 S20 full ｜ holmes 73/100 (B) G18 C19 D16 S20 lite ｜ jobs 50/100 (D) G12 C14 D11 S13 full · ⚠️ 总分<B · ⚠️ C<15 · ⚠️ D<12
告警与漂移（3 处）：⚠️ jobs-persona 来源材料已更新，建议重铸 ｜ ⚠️ 触发词冲突「帮我审一下」同属 jobs-persona、skeptic-cfo-persona（完全相同，必须消解） ｜ ⚠️ jobs-persona 状态降级 `active` → `draft`（总分 50 < B/70）
运行侧校准（CALIBRATION.md，见 §5.4）：skeptic-cfo-persona ✅ 存在 · 生效中 3 条 · 已撤销 1 条 · 待观察 1 条
使用反馈（人格缺陷才计入汇总）：munger-persona 人格缺陷 2 条 · 忠实沉默 1 条 · 规则缺口 0 条 —— 下一步由**用户**读反馈，决定是否修订源材料 · 共 4 个人格 · 总分 ≥B 的 3 个 · 生成力 G ≥12 的 4 个
```

> 四轴不齐或未跑质检的人格如实标 `未测`，**不得声称达标**；`mode lite` 只表示 P7 未跑（四个数不相加的规则见 §5.3）。

## 八、检查清单

- **落盘与字段**（§一 / §四）：人格在 `~/.claude/skills/<slug>-persona/`（用户级，不进 skill 仓库）且**自包含**（`SKILL.md` · `references/AXIOMS.md` · `FIDELITY.md`），目录名 = frontmatter `name`；必填七项 + 来源二选一齐全，`schema_version` 为 2（为 1 的已记入重铸计划），用 `axes` 承载四轴 + 总分/等级 + mode + 日期（非 `fidelity` / `generativity`）；`source_material_sha256` 由 `forge_scaffold.py` 写入，没记哈希须是**有意的通用输入**；`status` 按 §四 推导。
- **名册与冲突**（§三 / §六）：`roster.py` 能完整扫出、无解析错误；触发词是独有锚点（无通用词 / 完全相同重叠 / 子串包含）；无 slug 碰撞，`retired` 已从主表移出或明确标注。
- **漂移与回路**（§五）：跑过 `roster.py` 无 `stale` 报警；重铸是**从当前 ground truth 重铸**，不是改材料迁就人格；合成型 `references/AXIOMS.md` 在位且 `source_axioms_sha256` 一致；不向用户宣称「写反馈会自动触发重铸」。
- **反馈**（§5.2）：每条带 `evidence` + `material_sha256`，`context` ∈ {`session`, `review`, `eval`}；`faithful_silence` / `policy_gap` **不计入**缺陷汇总；`incoherent`（矛盾）与「内在张力」分开。
- **运行侧校准**（§5.4）：每条过**收窄测试**，无新增立场 / 放宽诚实边界 / 删反模式；带来源且「生效中」≤ 10 条；`incoherent` 条目只把矛盾收窄成张力（或删一条）；ground truth 更新后逐条重判、根因消失的移入「已撤销」（保留历史与理由）；P7 把 `CALIBRATION.md` 纳入攻击面，spawn prompt 同时给 `SKILL.md` 与 `CALIBRATION.md`。
