<div align="center">

# 拘神.skill

> 铸的是认知，立的是公理，成的是一个人。

</div>

**从你提供的信息里，铸出「一个人」的认知与思考模型。** 这个人可以是一个真实人物、一个虚构角色，
也可以**根本不存在**——三种情况共用同一条路径：

```
用户提供的信息  →  提炼  →  显式公理集  →  放大  →  完整认知 + 表达
（口述/主题/档案/原作/文献）    ↑                ↑
                          可审计的根        推导闭包
```

**公理集是对一个人的压缩，放大是解压**——为什么这条路径可行、可审计性指的是什么，
见 [`references/design-philosophy.md`](references/design-philosophy.md) §零。

## 它能做什么？

| 场景 | 说明 |
|------|------|
| **铸一个人** | 从你给的信息里铸出可运行的人格 skill，装进 `~/.claude/skills/` 即可被 harness 触发 |
| **提炼认知** | 先把信息收敛成 3-7 条**不可再分**的基本立场（公理集）——这是可审计的根 |
| **放大成人格** | 由公理集推出心智模型、决策启发式、表达DNA、诚实边界。**认知层是主产物**，人格层服务于它 |
| **用他的视角** | 铸好后直接说「用 XX 的视角看看…」，人格以那个人的身份回应，不需要任何额外协议 |
| **越用越准** | 失败经**两条速度不同**的回路回流：运行侧即时收窄，材料侧交回上游 |
| ❌ **不编排** | 不做多个人格之间的对话、不做多人会议、不分兵多路——那是**编排**，不是**铸造** |

> **铸好一个人，任务就结束了。** 人格怎么被用、和谁一起用，不是本 skill 的事。

## 设计哲学：六条公理

> **Canonical source：[`references/design-philosophy.md`](references/design-philosophy.md)。**
> 六条公理的定义、判据、射程与「公理 → 规则」映射表都在那边，**本文件不复制**。

一句话版本：**认知优先（1）· 先立公理再推导（2）· 生成力是目的（3）· 自洽但保留张力（4）·
可以不存在不可以冒充（5）· 人的边界先于任务（6）**。

规则冲突时看公理，遇到新情况**回公理推导**（`design-philosophy.md` §三）；
公理没覆盖的：如实说「本 skill 没覆盖」，按最保守方式处理并记 `policy_gap`——**不要就地编新规则**。

## 工作流

**开跑前先告诉用户代价**：全流程铸造合计 **≈ 9–10 个 agent**；轻量模式（lite，只跑 P3 攻击者 +
P5.5 + P6）**≈ 6–7 个**。

> 完整的 P0–P9 流程、逐阶段代价表、三种材料类型、四轴门槛、lite 的交付要求与产物落盘位置
> 见 [`SKILL.md`](SKILL.md) §五。

## 目录结构

```
summon-skill/
├── SKILL.md                       # 路由器：六公理索引、一个人格目录的产物模型、P0–P9 流程与代价表
├── README.md                      # 本文件
├── LICENSE                        # MIT
├── .gitignore
├── references/
│   ├── design-philosophy.md       # ⭐ 定位 + 六条公理（全 skill 的单一真相源）
│   ├── persona-forge.md           # ⭐ 铸人格方法论 + 公理集的格式 / 验收 / 模板（AXIOMS.md）
│   ├── persona-template.md        # 人格 SKILL.md 产物模板
│   ├── fidelity-scorecard.md      # P6 四轴评分：生成力 / 自洽性 / 辨识度 / 溯源
│   ├── adversarial-refine.md      # P7 对抗精炼（溯源攻击者 + 认知攻击者 + 四守卫）
│   └── roster-format.md           # 名册 + 漂移检测 + 使用反馈 + 运行侧校准（只许收窄）
├── scripts/
│   ├── _yaml_subset.py            # YAML 子集解析器（唯一实现，所有脚本共用）
│   ├── _material.py               # 源材料处理的共享实现（任意文件名 / 目录 / 路径）
│   ├── _spec.py                   # ⭐ 产物契约常量（四轴 / 门槛 / 红线 / 枚举 / 写边界，唯一实现）
│   ├── forge_scaffold.py          # 生成人格目录骨架 + 预填（材料 / 零文件 / 公理集三入口）
│   ├── fidelity_check.py          # 人格静态质检
│   ├── roster.py                  # 名册扫描 + 漂移 / stale 检测（严格只读）
│   ├── feedback_log.py            # 记录使用反馈（写人格自己的目录，强制证据指针）
│   ├── calibrate.py               # 运行侧校准（写 CALIBRATION.md，只许收窄）
│   ├── eval_record.py             # 四轴评测历史（EVALS.jsonl，追加式，不被覆盖）
│   └── selfcheck.py               # 仓库自检：文档 ↔ 脚本一致性（十五项）
├── tests/
│   ├── test_scripts.py            # 脚本行为回归测试
│   ├── test_yaml_subset.py        # 解析器回归测试
│   └── test_selfcheck.py          # 自检自身的回归测试
├── .github/
│   └── workflows/
│       └── ci.yml                 # CI：compileall + unittest + selfcheck + 示例质检
└── examples/
    └── skeptic-cfo-persona/       # 合成型人格完整示例（ground truth 是它的 references/AXIOMS.md）
        ├── SKILL.md
        ├── FIDELITY.md
        ├── README.md
        └── references/
            └── AXIOMS.md
```

人格装在用户级 `~/.claude/skills/<slug>-persona/`，装完即可被 harness 触发；
完整示例见 [`examples/skeptic-cfo-persona/`](examples/skeptic-cfo-persona/)。

## 自检

仓库自身的**文档 ↔ 脚本一致性**检查（十五项）：

```bash
python3 scripts/selfcheck.py
```

| # | 检查 | 它防的是什么 |
|---|------|-------------|
| 1–4 | 引用文件 / 废弃术语 / 路由表 / canonical source | 文档指向不存在的东西 |
| 5 | frontmatter 解析器唯一性 | 各脚本各写一份解析器（曾导致 `description` 正文覆盖 `status`） |
| 6–7 | 脚本 `--help` / README 目录树 | 新增脚本忘了登记 |
| 8–9 | 示例人格合规 / slug 漂移 | 示例产物自己不合规 |
| 10–11 | 文档 ↔ 脚本契约 / CI 存在性 | 声称脚本有它没有的能力 |
| **12** | **常量一致性** | 四轴分值、等级线、门槛、红线在 `_spec.py` 与文档之间不一致（曾出现「张力门槛在 5 处文档里是 ≥2、在脚本里是 ≥1」） |
| **13** | **概念重复（指针纪律）** | 同一段内容在两个文档里逐字重复——复制是漂移的根因 |
| **14** | **声明的脚本行为存在** | 文档写着「`X.py` 会核 Y」而实现并不存在（空头支票会让读者以为有机器在守） |
| **15** | **示例哈希声明一致** | 示例文档里写出的 sha256 与实际文件对不上（曾出现同一文件里两个哈希不一致，而 CI 全绿） |

## 安装

```bash
npx skills add ai4next/summon-skill
```

## 使用

```
铸一个怀疑论 CFO
帮我从这几份材料里铸一个人
提炼一下这个人的认知
这个人的思考模型是什么
用 XX 的视角看看这个方案
```

## 许可

MIT
