#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 铸人格脚手架

读一份蒸馏档案（DISTILLATE.md），生成 persona 目录骨架，并**预填能自动填的部分**：
frontmatter、诚实边界（从档案 gaps 逐条映射）、心智模型小节标题。

生成的骨架按**双核**组织：🧠 认知层（心智模型 · 决策启发式）＋ 🎭 人格层（身份卡 · 表达DNA · 反模式），
外加 ⚖️ 运行层（诚实边界 · 防漂移）。小标题带层级标注，**两层都必须填满**，只填一层不算人格运行体。

用法:
    python3 forge_scaffold.py <DISTILLATE.md 路径> --out <人格目录> [--type real]

选项:
    --out DIR     人格目录，如 ~/.claude/skills/munger-persona/
    --type NAME   real | archetype | fictional（默认 real）
    --force       覆盖已存在的 SKILL.md

示例:
    python3 forge_scaffold.py distilled/munger/DISTILLATE.md \\
        --out ~/.claude/skills/munger-persona --type real

产出:
    <out>/SKILL.md          预填骨架（需 agent 按 persona-template.md 补全）
    <out>/references/       空目录，备用

注意:
    本脚本只做**骨架预填**，不生成人格内容。表达DNA、决策启发式、Agentic Protocol
    必须由 agent 读 persona-forge.md 后自行推导。
"""

import hashlib
import os
import re
import sys
from datetime import date


def usage_error(msg):
    print("❌ " + msg)
    print("用法: python3 forge_scaffold.py <DISTILLATE.md 路径> --out <人格目录> [--type real]")
    sys.exit(1)


def strip_quotes(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_scalar(val):
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        return [strip_quotes(x) for x in inner.split(",")] if inner else []
    if val.startswith("{") and val.endswith("}"):
        out = {}
        for part in val[1:-1].split(","):
            if ":" in part:
                k, _, v = part.partition(":")
                out[strip_quotes(k)] = strip_quotes(v)
        return out
    return strip_quotes(val)


def parse_frontmatter(text):
    """解析契约限定的 YAML 子集。返回 (dict, body)；失败返回 (None, text)。"""
    if not text.lstrip().startswith("---"):
        return None, text
    start = text.index("---") + 3
    end = text.find("\n---", start)
    if end == -1:
        return None, text
    data, current_key = {}, None
    for line in text[start:end].splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line[:1] in (" ", "\t") and line.strip().startswith("- "):
            if current_key is not None and isinstance(data.get(current_key), list):
                data[current_key].append(strip_quotes(line.strip()[2:]))
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if not val:
            data[key] = []
            current_key = key
        else:
            data[key] = parse_scalar(val)
            current_key = None
    return data, text[end + 4:]


def section(body, title):
    m = re.search(r"^##\s+" + re.escape(title) + r"\s*$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    return m.group(1) if m else ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def build_skeleton(fm, body, slug, persona_type, archive_rel):
    title = fm.get("title", slug)
    name = "%s-persona" % slug
    gaps = fm.get("gaps", []) or []
    conf = fm.get("confidence", {}) or {}
    total = fm.get("sources_total", "?")
    a, b = conf.get("A", 0), conf.get("B", 0)
    try:
        pct = int(100.0 * (int(a) + int(b)) / max(1, int(a) + int(b) + int(conf.get("C", 0)) + int(conf.get("D", 0))))
    except (TypeError, ValueError):
        pct = "?"

    # 心智模型小节：从档案的「心智模型 / 核心框架」段抽 ### 标题
    models = re.findall(r"^###\s+(.+)$", section(body, "心智模型 / 核心框架"), re.M)
    if not models:
        models = re.findall(r"^###\s+(.+)$", body, re.M)

    gap_lines = "\n".join("- " + g for g in gaps) if gaps else "- [档案未列出明确缺口——请确认这是真的无缺口，还是没写]"

    if models:
        model_blocks = "\n\n".join(
            "### 模型%d: %s\n**一句话**：[待填]\n**证据**：[待填，标注信度等级]\n"
            "**应用**：[待填]\n**局限**：[待填]" % (i + 1, m.strip())
            for i, m in enumerate(models[:7])
        )
    else:
        model_blocks = "### 模型1: [待填]\n**一句话**：[待填]\n**证据**：[待填]\n**应用**：[待填]\n**局限**：[待填]"

    disclaimer = {
        "real": "我以[人格名]的视角和你聊，基于公开材料推断，非本人观点。",
        "archetype": "我是一个合成的[领域]原型人格，不对应任何具体个人，观点为框架推演。",
        "fictional": "我以[作品]中的[角色]身份回应，基于公开设定推演，不复现原作原文。",
    }.get(persona_type, "[待填免责声明]")

    return """---
name: {name}
description: |
  [人格名]的人格运行体。基于蒸馏档案 `{slug}`（{total} 个来源、一手占比 {pct}%）铸成。
  用途：[思维顾问 / 决策参考 / 角色扮演 / 圆桌对谈]。
  当用户提到「用[人格名]的视角」「[人格名]会怎么看」「召唤[人格名]」时使用。
  不要在一般性问题上自动触发——只在明确点名该人格，或问题落在其核心方法论时激活。
persona_type: {ptype}
source_distillate: {slug}
source_distillate_sha256: {sha}
source_distillate_version: {dver}
updated: {today}
triggers: [用[人格名]的视角, [人格名]会怎么看, [英文名] persona]
status: draft
---

# [人格名] · 人格运行体

> [一句最能代表此人格的原话]

## 使用说明

本 skill 激活后，直接以[人格名]的身份回应。想退出角色 → 说「退出」「切回正常」。

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
- **未表态主题标推断**：从未公开表态的领域，先说明「这是框架推断」再展开
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

[**由 agent 从下方心智模型反推生成 3-5 个研究维度**——见 persona-forge.md]

### Step 3: [人格名]式回答

基于 Step 2 获取的事实（如有），运用心智模型和表达DNA输出回答。

## 失败模式与 Fallback 树

| 触发条件 | 一线修复 | 仍失败兜底 |
|---------|---------|-----------|
| 研究工具不可用 | 改用等价工具 | 明说查不到最新情况，给条件性判断，不编事实 |
| 被问到档案未覆盖的领域 | 查「诚实边界」段 | 明说超出材料范围，给框架推断并标注 |
| 对话变长后人格漂移 | 回读「表达DNA」段 | 主动提示用户「我有点跑偏了」 |

## 反例黑名单（绝不要做）

| # | 反例 | 为什么 |
|---|------|--------|
| 1 | 编造此人没说过的话 | 引语必须有出处 |
| 2 | 替真人表态敏感议题 | 结构性沉默要忠实呈现 |
| 3 | 用通用 AI 腔 | 表达DNA 是硬约束 |
| 4 | 斩钉截铁回答未覆盖的问题 | 必须标注推断 |

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
   - 应用场景：[什么时候用]
   - 案例：[已知实例]

## 表达DNA · 🎭 人格层

角色扮演时必须遵循的风格规则：
- **句式**：[待填]
- **词汇**：[待填]
- **节奏**：[待填]
- **幽默**：[待填]
- **确定性**：[待填]
- **引用习惯**：[待填]

## 价值观与反模式 · 🎭 人格层

**我追求的**：[待填]
**我拒绝的**：[待填]
**我自己也没想清楚的**：[内在张力，至少 2 对]

## 诚实边界 · ⚖️ 运行层

此人格基于蒸馏档案 `{slug}` 铸造，存在以下局限：
{gaps}
- 档案截止：{today}，之后的变化未覆盖
- [真人型] 公开表达 vs 真实想法可能有差距

## 附录：调研信息源

源档案：`{archive}`（含 `research/` 分维度底稿与 `manifest.json`）

---

> 本Skill由 [拘神 · summon-skill](https://github.com/ai4next/summon-skill) 铸造
> 源档案：{slug}
""".format(name=name, slug=slug, total=total, pct=pct, sha="[待填]",
           ptype=persona_type, disclaimer=disclaimer, models=model_blocks,
           gaps=gap_lines, today=date.today().isoformat(), archive=archive_rel,
           dver=fm.get("version", "?"))


def main():
    argv = [a for a in sys.argv[1:]]
    if not argv:
        usage_error("缺少 DISTILLATE.md 路径")
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    src = os.path.abspath(os.path.expanduser(argv[0]))
    out = None
    persona_type = "real"
    force = False
    i = 1
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
            i += 2
        elif argv[i] == "--type" and i + 1 < len(argv):
            persona_type = argv[i + 1]
            i += 2
        elif argv[i] == "--force":
            force = True
            i += 1
        else:
            usage_error("无法识别的参数: " + argv[i])

    if not os.path.isfile(src):
        usage_error("档案不存在: " + src)
    if not out:
        usage_error("缺少 --out 人格目录")
    if persona_type not in ("real", "archetype", "fictional"):
        usage_error("--type 只能是 real / archetype / fictional，收到: " + persona_type)

    try:
        with open(src, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        usage_error("读取失败: %s" % e)

    fm, body = parse_frontmatter(text)
    if fm is None:
        usage_error("档案缺少 frontmatter，不符合 artifact-format.md 契约: " + src)

    missing = [k for k in ("slug", "title", "gaps") if k not in fm]
    if missing:
        print("⚠️  档案 frontmatter 缺少字段: %s（继续，但请检查契约符合性）" % "、".join(missing))

    slug = fm.get("slug") or os.path.basename(os.path.dirname(src))
    out_dir = os.path.abspath(os.path.expanduser(out))
    skill_path = os.path.join(out_dir, "SKILL.md")

    if os.path.exists(skill_path) and not force:
        print("❌ 已存在 %s" % skill_path)
        print("   人格已铸过。要重新生成请加 --force（会覆盖），或直接召唤现有人格。")
        sys.exit(1)

    os.makedirs(os.path.join(out_dir, "references"), exist_ok=True)

    skeleton = build_skeleton(fm, body, slug, persona_type,
                              os.path.relpath(src, out_dir))
    skeleton = skeleton.replace("source_distillate_sha256: [待填]",
                                "source_distillate_sha256: " + sha256_file(src))
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(skeleton)

    n_models = len(re.findall(r"^###\s+(.+)$", section(body, "心智模型 / 核心框架"), re.M)) or \
        len(re.findall(r"^###\s+(.+)$", body, re.M))
    gaps = fm.get("gaps", []) or []

    print("铸人格脚手架: %s" % slug)
    print("=" * 58)
    print("  ✅ 骨架已写入: %s" % skill_path)
    print("  类型: %s · 来源档案: %s" % (persona_type, slug))
    print("  已预填: frontmatter · 角色扮演规则 · 诚实边界（%d 条 gaps）· 心智模型 %d 个小节标题"
          % (len(gaps), min(n_models, 7)))
    print("  待填: 表达DNA · 决策启发式 · Agentic Protocol 研究维度 · 身份卡 · 示例对话")
    print("=" * 58)
    print("  下一步: 读 references/persona-forge.md 与 persona-template.md 补全，")
    print("          然后跑 scripts/fidelity_check.py 自检。")
    if not gaps:
        print("")
        print("  ⚠️  档案 gaps 为空——确认是真的无缺口，还是没写。诚实边界是地基。")


if __name__ == "__main__":
    main()
