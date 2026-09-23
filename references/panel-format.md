# 人格组规范（Panel Format）

> 人格组是**主持人侧**的可复用圆桌编排配置：它记下「这几个人凑一桌、该吵哪几架」，但**绝不告诉桌上任何人该吵什么**。

## 一、定位与归属
**panel（人格组）不是人格属性，是主持人（host）的编排配置。** 一个人格永远不知道自己被编进了哪个 panel——这正是它成立的前提。

| 产物 | 落盘 | 归属 | 谁读 |
|------|------|------|------|
| 蒸馏档案 | `distilled/<slug>/` | distill（只读） | distill 写，summon 只读 |
| 人格 | `~/.claude/skills/<slug>-persona/` | summon（人格本体） | harness 触发；**被 spawn 的 persona agent 读** |
| **人格组 panel** | `~/.claude/skills/panels/<slug>.panel.md` | summon（主持人侧） | **只有主持人读** |

**为什么是 `~/.claude/skills/panels/`**：

- **与人格同层（用户级）**：理由同 `roster-format.md` §一——放 `~/.claude/skills/` 下 harness 立即触发，`roster.py` 一次扫描就能把人格与 panel 一起收进名册。
- **独立 `panels/` 子目录，不塞进任何 `<slug>-persona/`，也不放 `distilled/`**：persona agent 的 spawn prompt 只给一个人格文件路径，但**目录若同处一地，隔离就只剩一句口头约定**——放远一点，让「读不到」成为物理事实而非纪律要求。`distilled/` 则是 distill 的地盘（`roster-format.md` §一「只读不写」），且档案是**用户知识数据**、panel 是**编排配置**，混放会把「档案可迁移、配置随环境」的界线糊掉。
- **后缀 `.panel.md` 而非目录**：panel 是**单文件配置**，没有 `SKILL.md` / `FIDELITY.md` 那一套；独立后缀让 `roster.py` 用 `*.panel.md` 与 `*-persona` 永不碰撞（同 `roster-format.md` §二 的命名空间隔离思路）。

---

## 二、最重要的约束：panel 绝不注入任何人格的上下文
**panel 文件绝不进入任何 persona agent 的 prompt。人格永远不知道自己「应该反对谁」。** 这不是风格偏好，是两条硬红线的交点。任何一条被踩，panel 就从「编排工具」变成「人格污染源」。

### 理由 1：违反**独立首次**
`summon-protocol.md` §四.3 规定：**圆桌第 1 轮必须互不可见**，「否则第一轮就会被最强的那个人格带跑」。

圆桌的全部价值在于**先独立表态，再交锋**。把「谁反对谁」预置进人格，等于**在第 1 轮之前就注入了对抗**——人格还没开口，立场已被编排指定，第 1 轮不再是盲测而是照剧本演，直接破坏 §四.3。

### 理由 2：替人格表态 → 自动触发判 D 红线
告诉一个人格「你反对 Y」，会让它为了配合编排而**断言一个档案里没有的立场**。回到 `fidelity-scorecard.md` §一.6 的断言 diff：档案中无对应却以确定口吻陈述 = **0 分（编造特质）**；而 §二 的分维度红线是——**档案一致性 = 0 → 直接判 D，不论总分**。

**也就是说：panel 的核心机制会把成员推入自动失败条件。** 一个越「好用」的 panel（对抗写得越明确），越会把成员打到 D。这是本格式最重要的设计约束。

### ✅ / ❌ 对照
| ✅ 允许 | ❌ 禁止 |
|--------|--------|
| panel 文件被**主持人**读取 | panel 文件出现在任何 persona agent 的 prompt 里 |
| `agenda` 只用于**第 2 轮**播种（第 1 轮已盲跑完） | 第 1 轮 prompt 里出现任何 agenda 内容 |
| 第 2 轮把争点作为**问题**抛出：「A 与 B 在 X 上分歧，你怎么看」 | 把立场作为**身份**下发：「你是反对 B 的一方」 |
| `sides` 作为**主持人的预期**，用于挑问题和判断收敛 | `sides` 作为**给 agent 的指令**；或落点不符时诱导其改口对齐 agenda |

**一句话**：`agenda` 是主持人手里的**提问清单**，不是人格头上的**角色标签**。

---

## 三、格式规范
### 3.1 frontmatter（YAML 子集）
必须落在 `artifact-format.md` §2.1 的 **YAML 子集**内（stdlib-only 脚本要能解析）：只允许 `key: 标量`、`key: [行内列表]`、`key: {行内映射}`、`key:` + `- 项` 块列表；**禁止**嵌套多行映射、多行字符串（`|` / `>`）、锚点别名、注释。含 `:` `#` `[` `]` `{` `}` 的标量加双引号。完整示例见 §八。

| 字段 | 必填 | 说明 |
|------|------|------|
| `schema_version` | ✅ | 契约版本，当前 `1` |
| `panel` | ✅ | panel slug，与文件名 `<slug>.panel.md` 一致 |
| `topic` | ✅ | 这桌要谈的议题，一句话 |
| `source_archive` | ✅ | **播种本 panel 的 topic 档案 slug**（`schema: topic`，或沿用 topic schema 的综合档案）。`agenda` 每一条都必须能回溯到它的分歧段 |
| `members` | ✅ | 人格 slug 列表，**≥2**。全部须存在于 `~/.claude/skills/<slug>-persona/` 且非 `retired` |
| `formations` | ✅ | 允许的阵型白名单，取自 `duet` / `roundtable` / `dispatch`。默认 `[roundtable]` |
| `updated` | ✅ | 最后修改日期 `YYYY-MM-DD` |

**`agenda` 不在 frontmatter 里**——它是结构化内容，写进正文（YAML 子集禁多行嵌套，硬塞会解析失败）。

### 3.2 正文：`agenda`
正文只放一段 `## agenda`，每条争点四项：

| 项 | 含义 | 来源 |
|----|------|------|
| `issue` | 争点本身 | `schema-topic.md` §一「02 流派分歧」的核心主张对撞 |
| `sides` | 哪位成员落在哪一侧 | 「流派对比表」的流派行 → 映射到人格 |
| `root` | **断层线性质** | 「流派对比表」的「**与对立派的分歧根源**」列：**事实**不一致，还是**价值排序**不一致 |
| `trace` | 证据指针 | 同 `FEEDBACK.jsonl` 的 `evidence` 原则：**无指针 = 意见，不是 agenda** |

**`root` 决定这条争点会不会收敛**：`事实分歧` 可靠第 2 轮交锋收敛；`价值观分歧` **不可调和**，`schema-topic.md` §一明确要求「必须保留」。主持人汇总时不要对后者和稀泥（`summon-protocol.md` §三 主持人红线）。

---

## 四、组队原则
| 原则 | 说明 |
|------|------|
| **优先真断层线** | 成员要落在**档案里本来就存在的分歧**两侧。`schema-topic.md` §二 的**丙级（流派分歧）**条目是选人第一依据——「丙是骨架的主力」 |
| **禁止制造冲突** | ❌ 档案里各派其实一致，却硬凑一个「反方」——这是**「不调和分歧」的镜像失败**：前者把真分歧揉平，后者把假分歧捏出来，两者都让汇总失真 |
| **落点须有档案支撑** | 成员的每一侧都必须能在**它自己的档案**里找到对应条目；找不到 → 它会在第 2 轮编造立场 → `档案一致性 = 0` → 判 D（§二 理由 2） |
| **三型可混编** | `real` / `archetype` / `fictional` 都能进 panel。原型型（如「怀疑论 CFO」）尤其适合充当**档案里没有对应真人**的那一派——它本就声明是合成的，没有保真度包袱 |
| **必须存在且可用** | 成员须已铸造、`name` 与目录一致、`status` 非 `retired`。`stale`（档案已变）与 `draft`（保真度 <B）→ **警告但仍可上桌**，须在汇总里标注该成员独立性偏弱 |
| **2-5 人** | 与圆桌阵型上限一致（`summon-protocol.md` §一）。超过 5 人 → 拆成两个 panel，或改用**遣将** |

**流派 → 人格的映射是 panel 的核心工作量**：档案里的分歧是**流派**之间的，panel 要把它落到**人格**身上。一个流派可能对应多个人格（选档案最厚、保真度最高的那个），一个人格也可能同时站在多条断层线上。

**panel 编排的是 🧠 认知层，不是 🎭 人格层。** `agenda` 只写「这几派在哪条断层线上分歧」，**绝不写「谁该用什么语气」**——
语气属于各人格自己的「表达DNA」，由人格文件决定。把语气写进 agenda，就是在替人格规定表达方式，
与「替人格表态」属于同一类越界（§二 理由 2），而且第 2 轮一注入，读起来就是编排痕迹而不是分歧。

---

## 五、与圆桌的衔接
panel 是**圆桌的预置件**，不是圆桌的替代品。全程隔离点如下：

| 阶段 | 主持人动作 | 隔离状态 |
|------|-----------|---------|
| **前** | 读 panel 文件（只有它读）；校验 `members` 存在且非 `retired`；按 `topic` 备人 | panel 内容**停留在主持人上下文里**，不进入任何 spawn prompt |
| **第 1 轮** | 按 `summon-protocol.md` 阵型 3 并行 spawn N 个 agent，各拿原问题 | **互不可见、无提示**。spawn prompt 与本 panel **零交集**——这是「独立首次」的落地 |
| **轮间** | 读第 1 轮发言，对照 `agenda` 的 `issue`：**谁落在哪一侧**；标出 agenda 未预料的新争点 | 只读不注入 |
| **第 2 轮** | 把上一轮**发言全文显式粘贴**（协议 §四.2：不共享上下文），再把 agenda 争点作为**问题**追加 | 人格此时才知道「别人说了什么」——但**仍不知道「自己被安排在谁对面」** |
| **后** | 按圆桌汇总格式产出；`分歧在哪` 段**优先呈现 `root: 价值观分歧` 的未决项** | 汇总只写事实，不回写 panel |

第 2 轮 prompt 的正确写法（对照 §二 ✅/❌）：

```
✅ 「上一轮 [A] 主张…，[B] 主张…。请以 [C] 的身份回应：你更认同谁，为什么，有没有被说服而需要修正的判断。」
❌ 「你是 [B] 的反方，请反驳 [B]。」
```

**两条纪律**：
1. **第 1 轮的结果优先于 agenda**：若第 1 轮冒出 agenda 未写、但真实存在的断层线——**它比 agenda 更有价值**（agenda 是赛前预测，这是实测），汇总时优先呈现，并回头补进 panel。
2. **落点不符不是失败**：成员实际落点与 `sides` 不符 → 要么组队错了（该换人），要么它的档案与所属流派本就偏离。**记录并更新 panel**，绝不诱导改口——那正是 §二 理由 2 的「替人格表态」。

---

## 六、校验规则
panel 有效的判据（`roster.py` 与人工自检共用同一套）：

| # | 规则 | 失败处理 |
|---|------|---------|
| 1 | `members` ≥ 2，且每个成员 `~/.claude/skills/<slug>-persona/` 存在、`name` 一致 | ❌ 报错：少于 2 人组不成圆桌（用单召）；成员缺失则先铸 |
| 2 | 无成员 `status: retired` | ❌ 报错：换人或先从 panel 移除 |
| 3 | 无成员 `stale` / `draft` | ⚠ 警告：可上桌，但汇总须标注独立性偏弱 |
| 4 | `source_archive` 存在且 `schema: topic`（或沿用 topic schema 的综合档案） | ❌ 报错：分歧图谱没有来源 |
| 5 | `agenda` ≥1 条，每条齐备 `issue` / `sides` / `root` / `trace` | ❌ 报错：字段不全 |
| 6 | `root ∈ {事实分歧, 价值观分歧}`；`sides` 里的 slug 全部 ∈ `members` | ❌ 报错：断层线未定性，或 agenda 指向桌外的人 |
| 7 | 每条 `agenda` 能回溯到 `source_archive` 的分歧段（流派对比表 / 丙级条目 / 一例多解案例） | ❌ **视为编造，删除该条**。这是 §四「禁止制造冲突」的机械检查 |
| 8 | `formations` 取值 ∈ `{duet, roundtable, dispatch}` | ❌ 报错 |

**第 7 条是硬门槛**：agenda 的合法性不来自「听起来有道理」，而来自**档案里确实有这组分歧**。回溯不到 → 那是编出来的戏。

---

## 七、与 roster.py 的关系
`roster.py` 仍是**只读脚本**（`roster-format.md` §三）：只报告，不自动改 panel、不自动换人。

| 步骤 | 动作 |
|------|------|
| 1 | 扫描 `~/.claude/skills/panels/*.panel.md`（与 `*-persona` 命名空间不碰撞） |
| 2 | 解析 frontmatter，抽出 `panel` / `topic` / `source_archive` / `members` / `formations` |
| 3 | 对每个成员**反查人格名册**：存在性、`status`、保真度、漂移 |
| 4 | 按第六节逐条校验，打印 panel 表与告警。输出形如 `value-investing-roundtable | 价值投资：安全边际还成立吗 | value-investing | munger-persona、taleb-persona、skeptical-cfo-persona | roundtable、duet | ✅ 可用`，成员有问题则附原因 |

**只读**：`roster.py` 只打印，**不写任何文件**（包括不写 `ROSTER.md`）。报告问题，不自动改 panel、不自动换人。

**与人格表的联动**：人格被 `retired` 或档案漂移 → 相关 panel 立即报 ⚠。panel 本身**不重铸**（它没有保真度），只需换人，或等成员重铸后自动恢复。

---

## 八、示例：价值投资圆桌
```markdown
---
schema_version: 1
panel: value-investing-roundtable
topic: "价值投资：安全边际还成立吗"
source_archive: value-investing
members: [munger-persona, taleb-persona, skeptical-cfo-persona]
formations: [roundtable, duet]
updated: 2026-09-22
---
## agenda
### 1. 内在价值可估吗——「便宜」是事实判断还是叙事判断？
- **issue**：价格低于内在价值即可买入，还是「内在价值」本身不可估、只能看尾部风险？
- **sides**：munger-persona → 可估；taleb-persona → 不可估，便宜可能是价值陷阱
- **root**：事实分歧
- **trace**：value-investing「流派对比表」第 1 行（价值派 vs 随机漫步派）
### 2. 集中持仓还是杠铃结构？
- **issue**：认知优势该集中下注，还是该用「极度保守 + 极小极度激进」的杠铃？
- **sides**：munger-persona → 集中；taleb-persona → 杠铃
- **root**：价值观分歧（对不确定性的态度：可知 vs 不可知，不可调和）
- **trace**：value-investing 案例库「LTCM 崩盘」的一例多解
### 3. 要不要主动对冲尾部风险？
- **issue**：为小概率崩盘持续付对冲成本，值不值？
- **sides**：skeptical-cfo-persona → 值；munger-persona → 不值，拖累复利
- **root**：价值观分歧
- **trace**：value-investing「流派对比表」第 3 行
```

**怎么用**：主持人先让三人**盲答**「现在还能不能谈安全边际」（第 1 轮，互不可见、不给 agenda）；拿到发言后对照三条 `issue` 看谁落在哪一侧，把**实际发生的**分歧（含 agenda 之外的）作为问题抛进第 2 轮。若第 1 轮三人一致认为「安全边际仍成立」，第 2 条争点根本不会发生——**如实呈现收敛，不硬凑**。

---

## 九、质检
- [ ] panel 落在 `~/.claude/skills/panels/<slug>.panel.md`，**不在**任何 `<slug>-persona/` 或 `distilled/` 下？
- [ ] frontmatter 只用 YAML 子集（无多行字符串、无嵌套多行映射、无注释）？`agenda` 在**正文**而非 frontmatter？
- [ ] **panel 文件从未进入任何 persona agent 的 prompt**？第 1 轮 prompt 与 agenda 零交集？
- [ ] 第 2 轮只把争点当**问题**抛，没有把 `sides` 当**身份**下发？
- [ ] 每条 agenda 都能回溯到 `source_archive` 的分歧段，没有编造的冲突？
- [ ] 成员 ≥2、全部存在、无 `retired`？`stale` / `draft` 已标注？
- [ ] 成员的落点都有**它自己的档案**支撑（否则会触发 `档案一致性 = 0` 判 D）？
- [ ] 第 1 轮实测出的新断层线，优先于 agenda 呈现，并已回写 panel？
- [ ] 汇总里 `价值观分歧` 被**保留**，没有被调和成温吞共识？跑过 `roster.py` 且 panel 表无告警？
