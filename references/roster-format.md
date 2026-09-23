# 人格名册规范（Roster Format）

> 已铸人格的索引：存在哪、怎么命名、有哪些字段、怎么检测漂移与冲突。

## 一、落盘位置

人格是**用户级 skill**，落在用户目录，不进任何 skill 仓库：

```
~/.claude/skills/<slug>-persona/
├── SKILL.md           # 人格本体（frontmatter + 六件套）
├── FIDELITY.md        # 保真度评分卡（当前快照，重跑会覆盖）
├── EVALS.jsonl        # 保真度评测历史（追加式，不被覆盖）——见 §5.3
├── FEEDBACK.jsonl     # 使用反馈（追加式）——见 §5.2
└── references/        # 可选：调研底稿、表达速查、案例库
```

**人格组（panel）** 落在并列目录，是**主持人侧的编排配置**，不是人格：

```
~/.claude/skills/panels/<slug>.panel.md    # 见 panel-format.md
```

**为什么放用户级而不是项目级**：放 `~/.claude/skills/` 后 harness 能**立即触发**——铸完就能用，不需要重启会话或改配置。项目级 skill 只在特定仓库生效，人格是跨项目复用的资产，放错层等于每次都要重铸。

**只读不写**：人格 skill 绝不修改 `distilled/<slug>/` 下的任何档案。档案归 distill 管，人格归 summon 管。**反向同理**：distill 也不写人格目录（只读 `FEEDBACK.jsonl`）。

## 二、命名规范

| | 命名 | 例 |
|---|------|-----|
| **人格运行体（本 skill 产物）** | `<slug>-persona` | `munger-persona`、`skeptical-cfo-persona` |
| 人格组（panel，主持人侧配置） | `<slug>.panel.md` | `value-investing.panel.md` |

**后缀固定为 `-persona`**，`roster.py` 只扫这个后缀（**命名空间隔离**）：

- 名册只收录本 skill 的产物，不误扫用户目录下的其他 skill（`~/.claude/skills/` 是共用目录，什么技能都可能装在那里）
- 一个人格一个目录，目录名与 frontmatter 的 `name` 必须一致，否则拒绝收录
- 同一份档案可以铸多次，但产物**目录名必须不同**（如 `munger-persona` 与 `munger-2026q3-persona`）——否则后铸的会覆盖先铸的

`<slug>` 沿用档案的 slug 规则：小写字母、数字、连字符（见 蒸馏.skill 仓库的 `artifact-format.md` 第一节）。

## 三、名册（Roster）

**名册是生成物，不是手写文件。** 不要手工维护一份索引——手工索引一定会和磁盘上的实际人格脱节。

`scripts/roster.py` 的职责：

| 步骤 | 动作 |
|------|------|
| 1 | 扫描 `~/.claude/skills/*-persona/SKILL.md` |
| 2 | 解析每个文件的 frontmatter，抽出名册字段（见第四节） |
| 3 | 读同目录的 `FIDELITY.md`，抽总分与等级 |
| 4 | 重算 `distilled/<slug>/DISTILLATE.md` 的 sha256，与 `source_distillate_sha256` 比对（漂移检测）。档案不在本地时，回落读 `manifest.json` 的 `distillate_sha256`（同一个值） |
| 5 | 两两比对 `triggers`，标记重叠（冲突检测） |
| 6 | 打印名册表（含漂移与冲突告警） |

**只读脚本**：`roster.py` **只读不写**，不修改任何文件。检测到漂移或冲突时**报告**，不自动改人格、不自动重铸。

## 四、名册字段

字段写在人格 `SKILL.md` 的 frontmatter 里，`roster.py` 直接解析：

```yaml
---
name: munger-persona
description: |
  查理·芒格的思维框架与表达方式。基于 distilled/munger 认知档案铸造，
  提炼 5 个心智模型、8 条决策启发式和完整表达DNA。
  当用户提到「用芒格的视角」「芒格会怎么看」「munger persona」时使用。
persona_type: real                  # real | archetype | fictional
source_distillate: munger           # 来源档案 slug
source_distillate_sha256: 3a71…     # 铸造时的档案哈希
source_distillate_version: 3        # 铸造时的档案版本
fidelity: {total: 88, grade: A, date: 2026-09-22}
updated: 2026-09-22
triggers: [用芒格的视角, 芒格会怎么看, munger persona, 逆向思考一下]
status: active                      # active | stale | draft | retired
---
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 必须是 `<slug>-persona` |
| `persona_type` | ✅ | `real` / `archetype` / `fictional`，决定免责声明写法（见 `persona-forge.md` 第三节） |
| `source_distillate` | ✅ | 来源档案 slug，与 `distilled/<slug>/` 目录名一致 |
| `source_distillate_sha256` | ✅ | **漂移检测依据**：铸造时 `DISTILLATE.md` 的内容哈希，由 `forge_scaffold.py` 自动写入（与 `manifest.json` 的 `distillate_sha256` 同值） |
| `source_distillate_version` | ✅ | 铸造时的档案 `version`，用于人读比对 |
| `fidelity` | ✅ | 内联映射：总分 / 等级 / 评测日期。来源是 `FIDELITY.md` |
| `updated` | ✅ | 人格最后修改日期 `YYYY-MM-DD` |
| `triggers` | ✅ | 触发词列表，**冲突检测依据** |
| `status` | ✅ | `active`（可用）/ `stale`（档案已变）/ `draft`（保真度 <B）/ `retired`（弃用） |

**`status` 的判定规则**（不靠人拍脑袋）：

| 条件 | 状态 |
|------|------|
| 保真度 ≥B 且哈希一致 | `active` |
| 保真度 <B | `draft` |
| 哈希不一致（档案变过） | `stale` |
| 用户显式弃用 | `retired` |

## 五、漂移检测

**问题**：人格是某一时刻从档案铸出来的快照。档案会随增量蒸馏升级（`version` +1、`gaps` 增删、`confidence` 变化），人格却停在原地——**档案已经更新，人格还在用旧认知说话**。

**机制**：`source_distillate_sha256` 记录铸造时 `DISTILLATE.md` 的内容哈希。`roster.py` 每次运行时**重算当前档案的哈希**并比对：

| 比对结果 | 判定 | 建议 |
|---------|------|------|
| 一致 | 人格与档案同步 | 无需动作 |
| 不一致 | **人格已陈旧（stale）** | 提示用户「档案已更新，建议重铸 `<slug>-persona`」 |

**重铸前先看差异**，不是所有变更都需要重铸：

| 档案变更 | 是否需重铸 |
|---------|-----------|
| 新增素材但骨架未变 | 否，可只更新「调研信息源」段 |
| `gaps` 增删 | **是**，诚实边界必须跟着变 |
| 核心骨架条目增删 | **是**，心智模型要重取 |
| `confidence` 中 D 级占比变化 >10% | **是**，诚实边界的措辞要调整 |
| 仅错别字/格式修订 | 否，重算哈希后刷新 `source_distillate_sha256` 即可 |

**关键**：档案是**只读**的。重铸 = 从当前档案重新铸一份人格，覆盖旧人格目录；**不是**去改档案来迁就人格。

### 5.1 漂移链路的真实触发点（重要）

**不要以为写了 `FEEDBACK.jsonl` 就会触发漂移检测。不会。**

`roster.py` 只哈希 `distilled/<slug>/DISTILLATE.md`。往人格目录追加 `FEEDBACK.jsonl` **不改变那个哈希**，所以漂移检测**不会**因此报错。

真实链路是：

```
使用中暴露失败 → summon 写 FEEDBACK.jsonl（人格目录）
                          ↓
        【人工】用户运行 distill 的「补充蒸馏」，distill 只读汇总 FEEDBACK
                          ↓
        distill 更新 gaps / 条目 → version++ → DISTILLATE.md 内容变 → 哈希变
                          ↓
        roster.py 这时才报 stale → 重铸人格 → 新分数记入 EVALS.jsonl
```

**触发点是 distill 的动作，不是 summon 的写入。** 这条链需要一次人工介入（跑补充蒸馏），不存在全自动闭环——如实描述，不要假装是自动的。

## 5.2 FEEDBACK.jsonl（人格使用反馈）

**位置**：`~/.claude/skills/<slug>-persona/FEEDBACK.jsonl` —— **在 summon 自己的地盘**，不是档案目录。

**归属原则**：档案归 distill 管，人格归 summon 管，**任何一方都不写对方的地盘**。distill 只读本文件，summon 只写本文件。

```json
{"schema_version":1,"date":"2026-09-22","persona":"munger-persona",
 "archive_sha256":"3a71…","formation":"roundtable",
 "question":"…","failure":"in_scope_gap","evidence":"档案 §决策启发式 第3条",
 "note":"…"}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | ✅ | 当前 `1` |
| `persona` | ✅ | 人格 slug |
| `archive_sha256` | ✅ | **使用时**档案的哈希——用于判断这条反馈针对哪一版档案 |
| `formation` | ✅ | 产生该反馈的阵型（`duet` / `roundtable` / `dispatch` / `review`） |
| `failure` | ✅ | 失败类型，见下表 |
| `evidence` | ✅ | **证据指针**（档案条目 / 行号 / 出处）。**无证据指针 → 是意见不是缺陷，distill 不得据此行动** |

### 失败类型分两类（关键）

| 类别 | 类型 | 含义 | 计入缺陷汇总？ |
|------|------|------|--------------|
| **人格缺陷** | `style_drift` | 表达不像（句式/词汇/节奏偏离表达DNA） | ✅ |
| | `in_scope_gap` | 问题**在该档案维度范围内**，却没答好 | ✅ |
| | `wrong_stance` | 人格立场与档案 A/B 级条目矛盾（**必须附反证指针**） | ✅ |
| **忠实沉默** | `faithful_silence` | 档案已标注该缺口 / 主体主动不公开 → **拒答是正确行为** | ❌ **不计入** |

> ⚠️ **`faithful_silence` 必须排除在缺陷汇总之外。**
> 拒答在本系统里常常是**正确行为**——gaps 映射、结构性沉默、伦理红线都要求拒答。
> 若把它当缺陷，distill 会被推着去「补上」这个缺口，从而**为刻意保持沉默的人编造立场**——这违反 `distillation-framework.md` §九「不要替他生成立场」，并被 `fidelity-scorecard.md` 判 **0 分**。
> 记录它是为了**统计忠实沉默的频率**，不是为了修它。

### 记录时机

- ✅ 多人阵型（双人对谈 / 圆桌 / 遣将）中主持人观察到的失败
- ✅ 事后复盘（用户读完回答后判定）
- ❌ **单召过程中不记录**——单召不 spawn，主 agent 就是人格，中途记录等于跳出角色（反模式 #10）。单召的失败留到事后复盘再记

## 5.3 EVALS.jsonl（保真度历史）

**问题**：`FIDELITY.md` 每次重铸都被覆盖，**分数历史随之销毁**——无法回答「重铸后比上一版好在哪」。

**解法**：追加式记录，只增不改。每行一条独立评测。

```json
{"schema_version":1,"run_id":"2026-09-22T11:00:00Z","version":3,
 "date":"2026-09-22","artifact_sha256":"7c1e…",
 "models":{"answer":"claude-sonnet-5","score":"claude-opus-5"},"scorers":2,
 "questions":[
   {"id":"q1","kind":"known","text":"…","status":"active"},
   {"id":"q4","kind":"out_of_scope","text":"…","status":"retired",
    "retired_reason":"该领域已被档案覆盖，不再是超范围题"}
 ],
 "scores":{"立场一致性":22,"风格辨识度":17,"边缘诚实度":13,
           "来源透明度":7,"结构完整度":15,"档案一致性":8},
 "total":82,"grade":"B","notes":"…"}
```

**题目内嵌在记录里，不做全局题库**——理由与档案侧相同：人格会变（缺口被补、条目被修正），全局固定题库会与之脱节。

**关键陷阱**：超范围题（`kind: out_of_scope`）的正确答案是「拒答 + 标注推断」。当档案补上该领域后，正确答案变成「真答」，而评分规则仍把拒答记为正确 → **越完整的人格分越低**（虚假退步）。所以：该领域被覆盖后，把该题标 `retired`，`compare` 会提示「本次对比无效」。

**追加纪律**：只追加，不改历史行；每条必须带 `models` 与 `scorers`（`scorers < 2` 时不给趋势结论）。

## 六、冲突检测

`roster.py` 每次运行检查三类冲突：

### 1. 触发词重叠

两两人格比对 `triggers`，出现交集即报警：

```
⚠ 触发词冲突：「逆向思考一下」同时属于 munger-persona 与 skeptical-cfo-persona
```

| 重叠程度 | 处理 |
|---------|------|
| 完全相同 | **必须消解**：改其中一个人格的触发词，或把该词从两者中都删掉 |
| 一方是另一方的子串（「芒格」vs「用芒格的视角」） | 保留长词，短词删除——短词会误触发 |
| 通用词（「帮我分析一下」） | 直接从 `triggers` 删除，通用词不该做人格触发 |

**原则**：触发词必须是**这个人格独有**的锚点。两个人格抢同一个触发词，等于两个 skill 抢同一个用户意图——harness 只能随机选一个，用户得到的是不确定的行为。

### 2. slug 碰撞

| 情况 | 处理 |
|------|------|
| `~/.claude/skills/<slug>-persona/` 已存在，但来源档案不同 | **报错**，要求改名或先 `retired` 旧人格 |
| `name` 字段与目录名不一致 | **报错**，`roster.py` 拒绝收录进名册 |
| 两个人格的 `source_distillate` 相同 | **警告**：同一档案铸了两次，确认是否有意为之 |

**状态冲突**：`status: active` 但 `FIDELITY.md` 缺失或保真度 <B → 降级 `draft` 并报警；`source_distillate` 指向的 `distilled/<slug>/` 已不存在 → 标 `stale`。

## 七、名册输出示例

```
$ python3 scripts/roster.py

人格名册 · 共 4 个 · 扫描自 ~/.claude/skills/*-persona/

| slug | 类型 | 来源档案 | 保真度 | 更新时间 | 触发词 | 状态 |
|------|------|---------|--------|---------|--------|------|
| munger-persona | real | munger @3a71f2 (v3) | 88 / A | 2026-09-22 | 用芒格的视角、芒格会怎么看 | active |
| skeptical-cfo-persona | archetype | finance-archetypes @b204e9 (v1) | 79 / B | 2026-09-20 | 怀疑论CFO、帮我审一下这张报表 | active |
| holmes-persona | fictional | holmes-canon @7c1d40 (v2) | 84 / B | 2026-09-18 | 福尔摩斯模式、用演绎法看看 | active |
| jobs-persona | real | jobs @0e55aa (v1) | 61 / C | 2026-09-15 | 乔布斯会怎么看 | draft |

⚠ 漂移 1 处：jobs-persona 的来源档案 jobs 已更新至 v2（sha256 0e55aa → 91ff03），人格基于 v1 铸造，建议重铸
⚠ 冲突 1 处：触发词「帮我审一下」同时属于 skeptical-cfo-persona 与 jobs-persona，请消解
⚠ 降级 1 处：jobs-persona 保真度 61 < B（70），已由 active 降为 draft

名册已写入 ~/.claude/skills/ROSTER.md
```

**表列说明**：`来源档案` 列同时给出 slug、哈希前 6 位与档案版本——**哈希前 6 位足够人眼比对**，全哈希只在脚本内部用。

## 八、检查清单

### 落盘与字段
- [ ] 人格在 `~/.claude/skills/<slug>-persona/`，不是项目级、不在 skill 仓库内？
- [ ] 目录里有 `SKILL.md` 与 `FIDELITY.md`？命名是 `<slug>-persona`，目录名与 frontmatter `name` 一致？
- [ ] 九个必填字段齐全？`name` 字段与目录名一致？
- [ ] `source_distillate_sha256` 由 `forge_scaffold.py` 自动写入（铸造时 `DISTILLATE.md` 的哈希），不是手填的？
- [ ] `status` 按第四节的规则判定，不是人拍的？

### 名册与冲突
- [ ] `roster.py` 能完整扫出该人格，无解析错误？
- [ ] 触发词都是该人格独有的锚点，无通用词、无子串重叠？
- [ ] 无 slug 碰撞？`retired` 的人格已从主表移出或明确标注？

### 漂移
- [ ] 跑过 `roster.py`，确认无 `stale` 报警（或已知晓并计划重铸）？
- [ ] 重铸是**从当前档案重铸**，而不是改档案去迁就人格？
