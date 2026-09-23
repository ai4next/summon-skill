#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 人格组（panel）脚手架

读一份综合档案（topic schema + 「## 分歧图谱」），生成 panel 骨架草案：
成员、对立关系、议题。

用法:
    python3 panel_plan.py <综合档案目录> --out ~/.claude/skills/panels/<slug>.panel.md \\
        [--members munger-persona,growth-persona] [--skills-dir ~/.claude/skills]

选项:
    --out PATH          输出 panel 文件路径
    --members LIST      指定成员（逗号分隔的人格 slug）；不给则从分歧图谱推断
    --skills-dir DIR    人格所在目录（默认 ~/.claude/skills），用于校验成员存在

核心约束（务必理解）:
    **panel 绝不注入任何人格的上下文。** 人格永远不知道自己「应该反对谁」。
    agenda 只供**主持人**在第 2 轮 seeding 使用，第 1 轮仍互不可见。
    理由见 references/panel-format.md（违反独立首次 + 替人格表态会判 D）。

只读档案，只在 --out 时写 panel 文件。
"""

import os
import re
import sys
from datetime import date

DIM_DIVERGENCE = ("流派分歧", "分歧图谱", "分歧")


def usage_error(msg):
    print("❌ " + msg)
    print("用法: python3 panel_plan.py <综合档案目录> --out <panel.md 路径> [--members a,b]")
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
    return strip_quotes(val)


def parse_frontmatter(text):
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


def section(body, *titles):
    for t in titles:
        m = re.search(r"^##\s+" + re.escape(t) + r"\s*$(.*?)(?=^##\s|\Z)", body, re.M | re.S)
        if m:
            return m.group(1)
    return ""


def find_personas(skills_dir):
    if not os.path.isdir(skills_dir):
        return []
    return [d for d in sorted(os.listdir(skills_dir))
            if d.endswith("-persona") and os.path.isdir(os.path.join(skills_dir, d))]


def main():
    argv = sys.argv[1:]
    if not argv:
        usage_error("缺少综合档案目录参数")
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    src = os.path.abspath(os.path.expanduser(argv[0]))
    out, members_arg = None, None
    skills_dir = os.path.expanduser("~/.claude/skills")
    i = 1
    while i < len(argv):
        if argv[i] == "--out" and i + 1 < len(argv):
            out = os.path.expanduser(argv[i + 1])
            i += 2
        elif argv[i] == "--members" and i + 1 < len(argv):
            members_arg = [m.strip() for m in argv[i + 1].split(",") if m.strip()]
            i += 2
        elif argv[i] == "--skills-dir" and i + 1 < len(argv):
            skills_dir = os.path.expanduser(argv[i + 1])
            i += 2
        else:
            usage_error("无法识别的参数: " + argv[i])

    if not os.path.isdir(src):
        usage_error("目录不存在: " + src)
    dpath = os.path.join(src, "DISTILLATE.md")
    if not os.path.isfile(dpath):
        usage_error("未找到 DISTILLATE.md，这不是一个档案目录: " + src)
    if not out:
        usage_error("缺少 --out")

    fm, body = parse_frontmatter(open(dpath, encoding="utf-8").read())
    if fm is None:
        usage_error("档案缺少 frontmatter")
    if fm.get("schema") != "topic":
        print("⚠️  档案 schema 是「%s」，不是 topic —— 综合档案应当是 topic schema" % fm.get("schema"))

    slug = fm.get("slug") or os.path.basename(src)
    title = fm.get("title", slug)

    # 从分歧维度抽议题
    # 注意：标题必须用 [^\n]+ 而非 .+ —— 本处用了 re.S，.+ 会贪婪吞掉后续所有小节
    div_text = section(body, *DIM_DIVERGENCE)
    agenda = []
    for m in re.finditer(r"^###[ \t]+([^\n]+)[ \t]*\n(.*?)(?=^###[ \t]|\Z)", div_text, re.M | re.S):
        issue = m.group(1).strip()
        block = m.group(2)
        sides = {}
        for sm in re.finditer(r"^\s*[-*]\s*\*{0,2}([^：:*]+)\*{0,2}\s*[:：]\s*(.+)$", block, re.M):
            who = sm.group(1).strip()
            # 「根源」不是成员，是议题的断层线说明，单独抽
            if who in ("根源", "断层线", "root"):
                continue
            sides[who] = sm.group(2).strip()[:40]
        root = ""
        rm = re.search(r"(?:根源|断层线)\s*[:：]\s*([^\n]+)", block)
        if rm:
            root = rm.group(1).strip()[:60]
        else:
            rm = re.search(r"(断层线|价值观分歧|事实分歧)[^\n]*", block)
            if rm:
                root = rm.group(0).strip()[:60]
        agenda.append({"issue": issue, "sides": sides, "root": root})

    # 成员推断
    available = find_personas(skills_dir)
    if members_arg:
        members = members_arg
    else:
        members = available
        if not members:
            print("⚠️  %s 下没有已铸人格，无法自动推断成员。" % skills_dir)
            print("    请先铸人格，或用 --members 显式指定。")

    missing = [m for m in members if m not in available]
    if missing:
        print("⚠️  以下成员尚未铸造: %s" % "、".join(missing))
        print("    请先用 summon 铸这些人格，或从 panel 里去掉。")

    # 写 panel 文件
    lines = [
        "---",
        "panel: %s-roundtable" % slug,
        "topic: %s" % title,
        "source_archive: %s" % slug,
        "members: [%s]" % ", ".join(members),
        "formations: [roundtable, dispatch]",
        "created: %s" % date.today().isoformat(),
        "updated: %s" % date.today().isoformat(),
        "---",
        "",
        "# %s · 人格组" % title,
        "",
        "> 本文件由**主持人**读取。**绝不注入任何人格的上下文**——",
        "> 人格永远不知道自己「应该反对谁」。agenda 只用于**第 2 轮** seeding，",
        "> 第 1 轮必须互不可见（见 summon-protocol.md §四 独立首次）。",
        "",
        "## Agenda（仅第 2 轮使用）",
        "",
    ]
    if agenda:
        for a in agenda:
            lines.append("### %s" % a["issue"])
            if a["sides"]:
                for who, stance in a["sides"].items():
                    lines.append("- **%s**：%s" % (who, stance))
            if a["root"]:
                lines.append("- 根源：%s" % a["root"])
            lines.append("")
    else:
        lines.append("（档案的分歧图谱为空或未按 `### 议题` 组织，需人工补议题）")
        lines.append("")

    lines += [
        "## 使用方式",
        "",
        "1. **第 1 轮**：按 summon-protocol.md 并行 spawn 各成员，各拿原问题，**互不可见**",
        "2. **主持人读本文件的 agenda**（成员看不到）",
        "3. **第 2 轮**：把上一轮发言 + 本文件的相关议题注入每个 agent 的 prompt",
        "4. 汇总时突出分歧，不要把分歧调和成共识",
        "",
        "## 校验",
        "",
        "- [ ] 所有成员都已铸造且状态非 retired/stale？",
        "- [ ] 每条议题都来自档案的分歧图谱，**不是编造的**？",
        "- [ ] 确认本文件不会被注入任何人格的 prompt？",
        "",
    ]

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    if os.path.exists(out):
        print("⚠️  %s 已存在，将被覆盖" % out)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("人格组脚手架: %s" % slug)
    print("=" * 62)
    print("  ✅ 已写入: %s" % out)
    print("  成员 %d 个: %s" % (len(members), "、".join(members) if members else "（无）"))
    print("  议题 %d 条（从档案分歧图谱抽取）" % len(agenda))
    for a in agenda[:5]:
        print("    · %s" % a["issue"][:50])
    if len(agenda) > 5:
        print("    ... 另有 %d 条" % (len(agenda) - 5))
    print("=" * 62)
    if not agenda:
        print("  ⚠️  未抽到议题——检查综合档案的「流派分歧」段是否用 `### 议题名` 组织。")
    if missing:
        print("  ⚠️  缺失成员: %s" % "、".join(missing))
    print("  记住：本文件只给主持人看，**不注入人格**。")


if __name__ == "__main__":
    main()
