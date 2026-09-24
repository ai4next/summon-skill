#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 铸人格脚手架

读一份 ground truth（**用户提供的源材料**——任意文件、任意文件名、任意目录，或
**合成型** `archetype` 的立场公理集 `AXIOMS.md`），生成 persona 目录骨架，并**预填能自动填的部分**：
frontmatter（含 ground truth 哈希与 `axes` 四轴占位）、诚实边界（「信息缺口」与
「闭包边界」分开）、心智模型小节标题。

**输入没有格式要求**（上位原则：`design-philosophy.md` §零）：
裸文本、没有 frontmatter、文件名不是 `MATERIAL.md`——**都能铸**。
`MATERIAL.md` / frontmatter 只是**可选约定**，用来让预填更完整、让漂移检测能工作。

材料类型（**三条平等主路径**）：实录型 `real` / 原作型 `fictional` / 合成型 `archetype`。
**合成型不是降级**——它没有保真包袱，但有更重的自洽 + 生成力责任；`--axioms` 是它的主路径。

生成的骨架按**双核**组织：🧠 认知层（心智模型 · 决策启发式）＋ 🎭 人格层（身份卡 · 表达DNA · 反模式），
外加 ⚖️ 运行层（诚实边界 · 防漂移）。小标题带层级标注，**两层都必须填满**。

用法（**三选一**，都通向同一个产物）:
    python3 forge_scaffold.py <任意材料文件或目录> --out <人格目录> [--type real|fictional]
    python3 forge_scaffold.py --axioms <AXIOMS.md 路径> --out <人格目录>      # 合成型主路径
    python3 forge_scaffold.py --source-desc "<来源描述>" --slug NAME --out <人格目录>   # 零文件

选项:
    --out DIR     人格目录，如 ~/.claude/skills/munger-persona/
    --type NAME   real | fictional | archetype（默认 real）
    --axioms PATH 合成型（archetype）的立场公理集（与位置参数二选一）——**主路径**
    --slug NAME   人格 slug（可选；不给则从 frontmatter 或路径推断）
    --force       覆盖已存在的 SKILL.md

示例:
    python3 forge_scaffold.py --source-desc "口述 2026-09-24，老王聊成本" \
        --slug laowang --out ~/.claude/skills/laowang-persona --type real
    python3 forge_scaffold.py 我的访谈记录.txt \\
        --out ~/.claude/skills/laowang-persona --type real --slug laowang
    python3 forge_scaffold.py material/munger/MATERIAL.md \\
        --out ~/.claude/skills/munger-persona --type real
    python3 forge_scaffold.py --axioms ./my-archetype/references/AXIOMS.md \\
        --out ~/.claude/skills/my-archetype-persona

产出:
    <out>/SKILL.md                 预填骨架（需 agent 按 persona-template.md 补全）
    <out>/references/AXIOMS.md     合成型：公理集副本（人格目录自包含、可迁移）

注意:
    本脚本只做**骨架预填**，不生成人格内容。表达DNA、决策启发式、Agentic Protocol
    必须由 agent 读 persona-forge.md 后自行推导。
    每条心智模型与启发式都会预置 `- **src**:` 行——那是公理 2 推导义务的机器可读形式，
    `fidelity_check.py` 会逐条核。
"""

import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _yaml_subset import (  # noqa: E402
    as_dict, as_int, as_list, as_str, parse_frontmatter, read_text, section, sha256_file,
)
from _material import (  # noqa: E402
    FIELD_SHA256, FIELD_SOURCE, FIELD_VERSION, MATERIAL_FILENAME, material_path,
)

#: 源材料里「核心骨架」段的候选标题（旧实现只找「核心框架」，因此永远落空）
MODEL_SECTION_TITLES = ("心智模型 / 核心骨架", "核心骨架", "心智模型 / 核心框架", "心智模型")

#: MATERIAL.md frontmatter 的候选字段——**每一项都可选**（见 `roster-format.md` §一）
REQUIRED_MATERIAL_FIELDS = ("slug", "title", "gaps")

DISCLAIMERS = {
    "real": "我以[人格名]的视角和你聊，基于公开材料推断，非本人观点。",
    "archetype": "我是一个合成的[领域]视角人格，不对应任何具体个人，观点为框架推演。",
    "fictional": "我以[作品]中的[角色]身份回应，基于公开设定推演，不复现原作原文。",
}

TYPE_BOUNDARY_LINES = {
    "real": "- 公开表达 vs 真实想法可能有差距",
    "archetype": "- **我不对应任何具体个人**，观点是框架推演，不是某位真人的立场",
    "fictional": "- 原作设定之外的部分为推演",
}


def die(msg, code=1):
    sys.stderr.write("❌ " + msg + "\n")
    sys.exit(code)


def warn(msg):
    sys.stderr.write("⚠️  " + msg + "\n")


def extract_models(body):
    """从「核心骨架」段抽 ### 标题。**只在匹配到的段内找**，绝不回落到全文。"""
    for title in MODEL_SECTION_TITLES:
        sec = section(body, title)
        if sec:
            models = [m.strip() for m in re.findall(r"^###\s+(.+)$", sec, re.M)]
            if models:
                return models
    return []


#: 合法 slug：小写字母 / 数字 / 连字符（`roster-format.md` §二）
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _sanitize_slug(raw):
    """把任意字符串收敛成合法 slug；收敛不出来 → None。"""
    s = re.sub(r"[^a-z0-9]+", "-", (raw or "").strip().lower()).strip("-")
    return s if s and SLUG_RE.match(s) else None


def _derive_slug(src, is_axioms):
    """从路径推断 slug。

    AXIOMS.md 惯例放在 `<人格目录>/references/AXIOMS.md`——此时取**祖父目录名**并去掉
    `-persona` 后缀，这样 `examples/skeptic-cfo-persona/references/AXIOMS.md` → `skeptic-cfo`。

    源材料**任意文件名都可以**：只有约定文件名 `MATERIAL.md` 才取**目录名**当 slug；
    其余情况取**文件本身的词干**——因为用户完全可能直接指着一个 `我的访谈记录.txt` 说「就铸这个」。
    """
    stem = os.path.basename(src).rsplit(".", 1)[0]
    parent = os.path.basename(os.path.dirname(src))
    if is_axioms:
        if parent in ("references", "ref", ""):
            grand = os.path.basename(os.path.dirname(os.path.dirname(src)))
            if grand.endswith("-persona"):
                grand = grand[: -len("-persona")]
            if grand:
                return grand
        return parent or stem
    if os.path.basename(src) == MATERIAL_FILENAME:
        return parent or stem
    return stem


def _source_ref(src, slug):
    """`source_material` 记什么。

    约定布局（文件名是 `MATERIAL.md`）→ 记 **slug**（人读友好、可移植）。
    任意文件（通用输入）→ 记 **路径**，否则 roster 之后再也找不到它，漂移检测就废了。
    路径优先相对当前目录；跑到 cwd 之外才退回绝对路径。
    """
    if os.path.basename(src) == MATERIAL_FILENAME:
        return slug
    rel = os.path.relpath(src, os.getcwd())
    return rel if not rel.startswith("..") else src


def extract_axioms(body):
    """从 AXIOMS.md 的公理表抽 (编号, 名称)。表形如 `| **A1** | **现金流的可信度…** | … |`。"""
    out = []
    for line in body.splitlines():
        m = re.match(r"^\|\s*\*\*(A\d+)\*\*\s*\|\s*\*\*(.+?)\*\*\s*\|", line.strip())
        if m:
            out.append((m.group(1), m.group(2).strip()))
    if out:
        return out
    # 回落：任何 `| **X** | **Y** |` 行
    for line in body.splitlines():
        m = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*\*\*(.+?)\*\*\s*\|", line.strip())
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def confidence_pct(fm):
    """一手占比。**没有 confidence 时返回「?」，绝不谎报 0%。**"""
    conf = as_dict(fm.get("confidence"))
    if not conf:
        return "?"
    nums = {}
    for k in ("A", "B", "C", "D"):
        v = as_int(conf.get(k), 0)
        nums[k] = v if v is not None else 0
    total = sum(nums.values())
    if total <= 0:
        return "?"
    return str(int(round(100.0 * (nums["A"] + nums["B"]) / total)))


def build_skeleton(fm, body, slug, persona_type, material_rel, sha, is_axioms,
                   axioms_rel=None, source_ref=None):
    title = as_str(fm.get("title")) or slug
    name = "%s-persona" % slug
    gaps = [g for g in as_list(fm.get("gaps")) if isinstance(g, str) and g.strip()]
    total = as_str(fm.get("sources_total"), "?")
    pct = confidence_pct(fm)
    cutoff = as_str(fm.get("updated")) or as_str(fm.get("version")) or "[待填]"
    today = date.today().isoformat()

    if is_axioms:
        axioms = extract_axioms(body)
        models = [a[1] for a in axioms]
        model_src = {a[1]: "AXIOMS.md#%s" % a[0] for a in axioms}
    else:
        models = extract_models(body)
        model_src = {m: "[材料条目 ID]" for m in models}

    if models:
        model_blocks = "\n\n".join(
            "### 模型%d: %s\n- **src**: %s\n**一句话**：[待填]\n**证据**：[待填，标注信度等级；"
            "`src: inferred` 时此处写推导链并点名所用的模型/启发式]\n"
            "**应用**：[待填]\n**局限**：[待填]" % (i + 1, m, model_src.get(m, "[材料条目 ID]"))
            for i, m in enumerate(models[:7])
        )
    else:
        model_blocks = ("### 模型1: [待填]\n- **src**: [材料条目 ID 或 inferred]\n"
                        "**一句话**：[待填]\n**证据**：[待填]\n**应用**：[待填]\n**局限**：[待填]")

    gap_lines = ("\n".join("- " + g for g in gaps) if gaps
                 else "- [材料未列出明确缺口——请确认这是真的无缺口，还是没写]")

    if is_axioms:
        gt_line = "立场公理集 `%s`（%d 条公理）" % (material_rel, len(models))
        source_block = ("source_axioms: %s\nsource_axioms_sha256: %s"
                        % (axioms_rel or "references/AXIOMS.md", sha))
    else:
        gt_line = "源材料 `%s`（%s 个来源、一手占比 %s%%）" % (slug, total, pct)
        _ver = as_str(fm.get("version"))
        source_block = ("%s: %s\n%s: %s\n%s: %s"
                        % (FIELD_SOURCE, source_ref or slug, FIELD_SHA256,
                           sha if sha else "null",
                           FIELD_VERSION, _ver if _ver else "null"))

    boundary_type_line = TYPE_BOUNDARY_LINES.get(persona_type, "")
    silence_line = ("- [材料显式标注的结构性沉默条目——**主动不公开 / 本质无立场，永远不补**]"
                    if not is_axioms else
                    "- [本合成人格在这些领域**本质无立场**：…（见公理集的「闭包边界」段）]")
    cut_line = ("- 公理集修订：%s，之后的变化未覆盖" % cutoff if is_axioms
                else "- 材料截止：%s，之后的变化未覆盖" % cutoff)

    return """---
schema_version: 2
name: {name}
version: 1
description: |
  [人格名]的人格运行体。基于{gt_line}铸成。
  用途：[思维顾问 / 决策参考 / 角色扮演 / 写作]。
  当用户提到「用[人格名]的视角」「[人格名]会怎么看」「让[人格名]来评评」时使用。
  不要在一般性问题上自动触发——只在明确点名该人格，或问题落在其核心方法论时激活。
persona_type: {ptype}
{source_block}
axes: {{生成力: 0, 自洽性: 0, 辨识度: 0, 溯源: 0, total: 0, grade: "—", mode: full, date: "{today}"}}
updated: {today}
triggers: []
status: draft
---

# [人格名] · 人格运行体

> [一句最能代表此人格的原话]

## 使用说明

本 skill 激活后，直接以[人格名]的身份回应。想退出角色 → 说「退出」「切回正常」。

> 若同目录存在 `CALIBRATION.md`（运行侧校准），**一并遵循**——它只收窄行为，不改变身份。

## 角色扮演规则（最重要）

### 🛑 STOP（仅一次）

**首次激活时，只说一次免责**：

> {disclaimer}

后续对话**不再重复**。

### 🚪 EXIT TRIGGER

用户说「退出」「切回正常」「不用扮演了」「停」→ 立即恢复正常模式，并简短确认。

### 角色硬规则

- 用「我」而非「[人格名]会认为…」
- 直接用此人格的语气、节奏、词汇回答
- 遇到不确定的问题，用此人格会有的犹豫方式犹豫，不要跳出角色
- **未表态主题标推断**：从未公开表态的领域，先说明「这是框架推断」**并点名所用的心智模型或启发式**
- **结构性沉默要忠实呈现**：刻意回避的领域，呈现那个沉默，不要替它生成立场
- **表达DNA是硬约束**：回答前默检下方「表达DNA」段

## 回答工作流（Agentic Protocol）

**核心原则：[人格名]不凭感觉说话。遇到需要事实支撑的问题时，先做功课再回答。**

### Step 1: 问题分类

| 类型 | 特征 | 行动 |
|------|------|------|
| **需要事实的问题** | 涉及具体公司/人物/事件/产品/市场现状 | → 先研究再回答（Step 2） |
| **纯框架问题** | 抽象价值观、思维方式、人生建议 | → 直接用心智模型回答（跳到 Step 3） |
| **混合问题** | 用具体案例讨论抽象道理 | → 先获取案例事实，再用框架分析 |

### Step 2: [人格名]式研究

**⚠️ 必须使用工具获取真实信息，不可跳过。**

[**由 agent 从下方心智模型反推生成 3-6 个研究维度**——见 persona-forge.md §五]

### Step 3: [人格名]式回答

基于 Step 2 获取的事实（如有），运用心智模型和表达DNA输出回答。

## 🔴 CHECKPOINT（关键节点自检）

### Checkpoint C：输出之前
- [ ] 表达DNA对得上？（句式/词汇/节奏/确定性）
- [ ] 未表态的领域标了「推断」**并点名了推导所用的模型**？
- [ ] 没跳出角色？

## 失败模式与 Fallback 树

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| 研究工具不可用 | 改用等价工具 | 明说查不到最新情况，给条件性判断，不编事实 |
| 被问到 ground truth 未覆盖的领域 | 查「诚实边界」段 | 明说超出材料范围，给框架推断并**点名推导链** |
| 对话变长后人格漂移 | 回读「表达DNA」段 | 主动提示用户「我有点跑偏了」 |

## 反例黑名单（绝不要做）

| # | 反例 | 为什么 |
|---|------|--------|
| 1 | 编造此人没说过的话 | 引语必须有出处 |
| 2 | 替真人表态敏感议题 | 结构性沉默要忠实呈现 |
| 3 | 用通用 AI 腔 | 表达DNA 是硬约束 |
| 4 | 斩钉截铁回答未覆盖的问题 | 必须标注推断 + 点名推导链 |

## 示例对话

**用户**：[典型问题]
**[人格名]**：[符合表达DNA的回答]

## 身份卡 · 🎭 人格层

**我是谁**：[50 字第一人称自我介绍，用此人格语气]
**我的起点**：[关键背景]
**我现在在做什么**：[最近动态，保持角色]

## 核心心智模型 · 🧠 认知层

{models}

## 决策启发式 · 🧠 认知层

1. **[规则名]**：[具体描述]
   - **src**: [材料条目 ID 或 inferred]
   - 应用场景：[什么时候用]
   - 案例：[已知实例]
   - 失效条件：[材料标注的失效条件——**必填**]

## 表达DNA · 🎭 人格层

角色扮演时必须遵循的风格规则（**六项全部必填，且必须可执行、可计数**）：
- **句式**：[待填]
- **词汇**：[待填]
- **节奏**：[待填]
- **幽默**：[待填]
- **确定性**：[待填]
- **引用习惯**：[待填]

## 价值观与反模式 · 🎭 人格层

**我追求的**：[待填]
**我拒绝的**：[待填]
**我自己也没想清楚的**：[内在张力，至少 1 对；写法是**人格自己承认这个冲突**，不是并列摆着两句相反的话]

## 诚实边界 · ⚖️ 运行层

此人格基于{gt_line}铸造，存在以下局限：

**信息缺口**（该有而没查到——需要时回补）：
{gaps}
{cut_line}
{type_line}

**闭包边界 / 结构性沉默**（主动不公开 / 本质无立场——**永远不补**，公理 5）：
{silence}

## 附录：调研信息源

ground truth：`{archive}`

---

> 本Skill由 [拘神 · summon-skill](https://github.com/ai4next/summon-skill) 铸造
> ground truth：{slug}
""".format(name=name, slug=slug, gt_line=gt_line, pct=pct, total=total,
           source_block=source_block, ptype=persona_type,
           disclaimer=DISCLAIMERS.get(persona_type, "[待填免责声明]"),
           models=model_blocks, gaps=gap_lines, today=today, cut_line=cut_line,
           type_line=boundary_type_line, silence=silence_line, archive=material_rel)


def main():
    ap = argparse.ArgumentParser(
        prog="forge_scaffold.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("material", nargs="?",
                    help="材料路径：**任意文件或目录**（与 --axioms / --source-desc 三选一）")
    ap.add_argument("--out", help="人格目录（必填）")
    ap.add_argument("--type", default="real", choices=("real", "archetype", "fictional"),
                    help="人格类型（默认 real；archetype = 合成型，三条平等主路径之一）")
    ap.add_argument("--axioms", help="合成型（archetype）的立场公理集 AXIOMS.md"
                                     "（与位置参数二选一）——合成型的主路径")
    ap.add_argument("--slug", help="人格 slug（可选；不给则从 frontmatter 或路径推断）")
    ap.add_argument("--source-desc",
                    help="零文件入口：只给来源描述（口述 / 书名 / 粘贴文本的标签）。"
                         "与位置参数、--axioms 三选一")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 SKILL.md")
    args = ap.parse_args()

    if not args.material and not args.axioms and not args.source_desc:
        die("缺少 ground truth：给出材料路径（**任意文件/目录**），\n"
            "   或用 --axioms 指定立场公理集（合成型），\n"
            "   或用 --source-desc 只给来源描述（材料只在对话里，没有文件）。")
    if sum(bool(x) for x in (args.material, args.axioms, args.source_desc)) > 1:
        die("材料路径 / --axioms / --source-desc 三者只能给一个")
    if not args.out:
        die("缺少 --out 人格目录")

    is_axioms = bool(args.axioms)
    zero_file = bool(args.source_desc)
    if zero_file:
        # **零文件入口**：材料只在对话里（口述 / 粘贴文本）。
        # 不要求用户留下文件——代价只是漂移检测报 none（design-philosophy.md §零）。
        src = None
    else:
        src = os.path.abspath(os.path.expanduser(args.axioms or args.material))
    if src and not is_axioms and os.path.isdir(src):
        # 允许直接给目录：自动找其中的 ground truth 文件（MATERIAL.md / 唯一 .md / 旧名）
        found = material_path(os.path.dirname(src), os.path.basename(src.rstrip(os.sep)))
        if not found:
            die("目录里找不到可作为 ground truth 的文件（%s）。\n"
                "   请直接指定要读的那个文件——**任意文件名都可以**，不要求整理成某种格式。"
                % src)
        src = found
    if src and not os.path.isfile(src):
        die("ground truth 不存在: " + src)

    out_dir = os.path.abspath(os.path.expanduser(args.out))
    skill_path = os.path.join(out_dir, "SKILL.md")
    if os.path.exists(skill_path) and not args.force:
        sys.stderr.write("❌ 已存在 %s\n" % skill_path)
        sys.stderr.write("   人格已铸过。要重新生成请加 --force（会覆盖），或直接使用现有人格。\n")
        sys.exit(1)
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        die("--out 指向的不是目录: " + out_dir)

    if zero_file:
        fm, body = {}, ""
    else:
        try:
            text = read_text(src)
        except OSError as e:
            die("读取失败: %s" % e)
        fm, body = parse_frontmatter(text)
    if fm is None:
        # **输入没有格式要求**：材料可以是一段裸文本 / 任意文件，没有 frontmatter 也照铸。
        # 缺口与截止日留占位符，由 agent 在 P2/P4 自己补（见 `roster-format.md` §一）。
        fm, body = {}, text
        if not is_axioms:
            warn("材料没有 frontmatter——照常生成骨架；`gaps` 与截止日留占位符，"
                 "请在 P2 自己记缺口（`roster-format.md` §一）")
        m = re.search(r"^#\s+(.+)$", body, re.M)
        if m:
            fm["title"] = m.group(1).strip()

    if not is_axioms:
        missing = [k for k in REQUIRED_MATERIAL_FIELDS if k not in fm]
        if missing:
            warn("材料 frontmatter 没给 %s——这些**全部可选**，照常继续"
                 "（`roster-format.md` §一）" % "、".join(missing))
        persona_type = args.type
    else:
        persona_type = "archetype"

    # slug：frontmatter → --slug → 路径推断；一律收敛成合法 slug
    raw_slug = as_str(fm.get("slug")) or args.slug
    if raw_slug:
        slug = _sanitize_slug(raw_slug)
        if not slug:
            die("slug `%s` 不合法：只能用**小写字母 / 数字 / 连字符**（如 `munger`）" % raw_slug)
    else:
        slug = _sanitize_slug(_derive_slug(src, is_axioms)) if src else None
        if not slug:
            die("无法确定人格 slug——请用 `--slug` 指定人格名，如 `--slug munger`。\n"
                "   （这只影响**人格目录名**，不影响你给的源材料格式。）")

    sha = sha256_file(src) if src else None

    try:
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(os.path.join(out_dir, "references"), exist_ok=True)
    except OSError as e:
        die("创建目录失败: %s" % e)

    axioms_rel = None
    if is_axioms:
        # 把公理集复制进人格目录，让人格目录**自包含、可迁移**（persona-forge.md §七）
        dest = os.path.join(out_dir, "references", "AXIOMS.md")
        try:
            import shutil
            shutil.copyfile(src, dest)
        except OSError as e:
            die("复制公理集失败: %s" % e)
        sha = sha256_file(dest)
        axioms_rel = os.path.relpath(dest, out_dir).replace(os.sep, "/")

    if zero_file:
        source_ref = args.source_desc
        material_rel = args.source_desc
    else:
        source_ref = _source_ref(src, slug)
        material_rel = os.path.relpath(src, out_dir)

    skeleton = build_skeleton(fm, body, slug, persona_type,
                              material_rel, sha, is_axioms,
                              axioms_rel, source_ref=source_ref)
    try:
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skeleton)
    except OSError as e:
        die("写入失败: %s" % e)

    n_models = len(extract_axioms(body)) if is_axioms else len(extract_models(body))
    gaps = [g for g in as_list(fm.get("gaps")) if isinstance(g, str) and g.strip()]

    print("铸人格脚手架: %s" % slug)
    print("=" * 58)
    print("  ✅ 骨架已写入: %s" % skill_path)
    if is_axioms:
        gt_desc = "AXIOMS.md"
    elif zero_file:
        gt_desc = "对话口述（无文件）"
    else:
        gt_desc = os.path.basename(src)
    print("  类型: %s · ground truth: %s (%s)" % (persona_type, slug, gt_desc))
    print("  已预填: frontmatter（%s）· 角色扮演规则 · 诚实边界（%d 条 gaps）"
          "· 心智模型 %d 个小节标题（带 src: 占位）"
          % ("含哈希 %s…" % sha[:6] if sha else "无哈希——零文件输入，漂移检测不可用",
             len(gaps), min(n_models, 7)))
    print("  待填: 表达DNA（六项）· 决策启发式（带失效条件）· Agentic Protocol 研究维度"
          "· 身份卡 · 示例对话 · src: 溯源指针")
    print("=" * 58)
    print("  下一步: 读 references/persona-forge.md 与 persona-template.md 补全，")
    print("          然后跑 scripts/fidelity_check.py 自检。")
    if not is_axioms and not gaps:
        print("")
        print("  ⚠️  材料 gaps 为空——确认是真的无缺口，还是没写。诚实边界是地基。")
    if is_axioms and n_models == 0:
        print("")
        print("  ⚠️  没能从 AXIOMS.md 解析出公理表——请确认格式（见 persona-forge.md §七）。")


if __name__ == "__main__":
    main()
