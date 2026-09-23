#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 人格静态质检

对 persona 的 SKILL.md 做 6 项结构检查（Phase 3 安装后自检）。

检查项覆盖双核：🧠 认知层（心智模型数量 · 模型局限性）＋ 🎭 人格层（表达DNA 辨识度）
＋ ⚖️ 运行层（诚实边界 · 内在张力 · 防漂移机制）。

用法:
    python3 fidelity_check.py <persona SKILL.md 路径>

退出码:
    0 = 6 项全过
    1 = 有未通过项，或参数/文件有误

注意:
    本脚本只做**静态结构检查**——它发现不了「人格跑起来像不像」。
    立场一致性与风格辨识度必须由独立 agent 跑 references/fidelity-scorecard.md，
    绝不能用本脚本代替，也绝不能自评。
"""

import os
import re
import sys


def usage_error(msg):
    print("❌ " + msg)
    print("用法: python3 fidelity_check.py <persona SKILL.md 路径>")
    sys.exit(1)


def strip_quotes(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


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
            data[key] = strip_quotes(val)
            current_key = None
    return data, text[end + 4:]


def section(body, *titles):
    """取某个二级标题下的正文。

    标题允许带层级后缀（如「## 表达DNA · 🎭 人格层」「## 诚实边界：说明」）——
    persona-template.md 用后缀标注双核归属，这里必须容忍，否则生成物会被误判缺段。
    """
    for t in titles:
        m = re.search(
            r"^##\s+" + re.escape(t) + r"(?:[ \t]*[·:：—\-|/][^\n]*)?[ \t]*$(.*?)(?=^##\s|\Z)",
            body, re.M | re.S)
        if m:
            return m.group(1)
    return None


def check_models(body):
    sec = section(body, "核心心智模型", "心智模型")
    if sec is None:
        return False, "缺少「核心心智模型」段"
    n = len(re.findall(r"^###\s+\S", sec, re.M))
    if n == 0:
        n = len(re.findall(r"^\s*(?:[-*]|\d+\.)\s+\S", sec, re.M))
    if n < 3:
        return False, "心智模型仅 %d 个（需 3-7）" % n
    if n > 7:
        return False, "心智模型 %d 个（>7，没取舍）" % n
    return True, "%d 个心智模型 ✅" % n


def check_limitations(body):
    if not re.search(r"局限|失效|不适用|盲区|limitation", body):
        return False, "未检出任何「局限」标注（每个模型都要写失效条件）"
    n = len(re.findall(r"\*\*局限\*\*|局限[:：]", body))
    return True, "%d 处局限标注 ✅" % n if n else "有局限标注 ✅"


def check_expression_dna(body):
    sec = section(body, "表达DNA", "表达 DNA", "表达风格")
    if sec is None:
        return False, "缺少「表达DNA」段——人格层缺失，产物只剩认知层（一套方法论，召不出「谁」）"
    markers = ["句式", "词汇", "节奏", "幽默", "确定性", "引用", "口头禅", "语气"]
    found = [m for m in markers if m in sec]
    if len(found) < 3:
        return False, "表达DNA 仅 %d 个风格标记（需 ≥3）: %s" % (len(found), "、".join(found) or "无")
    if "[待填]" in sec or "待填" in sec:
        return False, "表达DNA 段仍有「待填」占位符"
    return True, "%d 个风格标记: %s ✅" % (len(found), "、".join(found))


def check_honest_boundary(body):
    sec = section(body, "诚实边界", "Honest Boundary")
    if sec is None:
        return False, "缺少「诚实边界」段"
    items = re.findall(r"^\s*[-*]\s+\S", sec, re.M)
    if len(items) < 3:
        return False, "诚实边界仅 %d 条（需 ≥3）" % len(items)
    if "[档案未列出明确缺口" in sec:
        return False, "诚实边界未映射源档案 gaps（仍是占位符）"
    return True, "%d 条诚实边界 ✅" % len(items)


def check_tensions(body):
    sec = section(body, "价值观与反模式", "内在张力", "矛盾与张力")
    scope = sec if sec is not None else body

    # 优先数「我自己也没想清楚的」小节下的条目——真实人格很少每列一条都重复「张力」二字
    n_items = 0
    m = re.search(r"\*\*我自己也没想清楚的\*\*[^\n]*\n(.*?)(?=\n\*\*|\n##|\Z)", scope, re.S)
    if m:
        n_items = len(re.findall(r"^\s*(?:\d+\.|[-*])\s+\S", m.group(1), re.M))
    # 回落到关键词计数（张力/矛盾/tension/paradox）
    n_kw = len(re.findall(r"张力|矛盾|tension|paradox", scope))
    n = max(n_items, n_kw)

    if n < 2:
        return False, "内在张力仅 %d 处（需 ≥2，观点高度一致 = 太假）" % n
    if n_items:
        return True, "%d 处内在张力（列于「我自己也没想清楚的」）✅" % n_items
    return True, "%d 处内在张力 ✅" % n_kw


def check_drift_guard(body):
    missing = []
    if not re.search(r"角色扮演规则", body):
        missing.append("角色扮演规则")
    if not re.search(r"STOP|🛑", body):
        missing.append("STOP（首次免责）")
    if not re.search(r"EXIT|退出", body):
        missing.append("EXIT TRIGGER（退出触发）")
    if not re.search(r"表达DNA|表达 DNA", body):
        missing.append("表达DNA 硬约束")
    if missing:
        return False, "防漂移机制缺失: " + "、".join(missing)
    return True, "角色扮演规则 + STOP + EXIT + 表达DNA ✅"


def main():
    if len(sys.argv) < 2:
        usage_error("缺少 SKILL.md 路径参数")

    path = os.path.abspath(os.path.expanduser(sys.argv[1]))
    if not os.path.isfile(path):
        usage_error("文件不存在: " + path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        usage_error("读取失败: %s" % e)

    fm, body = parse_frontmatter(text)

    checks = [
        ("心智模型数量", check_models(body)),
        ("模型局限性", check_limitations(body)),
        ("表达DNA 辨识度", check_expression_dna(body)),
        ("诚实边界", check_honest_boundary(body)),
        ("内在张力", check_tensions(body)),
        ("防漂移机制", check_drift_guard(body)),
    ]

    print("人格质检: %s" % os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path))
    print("=" * 62)
    passed = 0
    for name, (ok, detail) in checks:
        print("  %-18s %s  %s" % (name, "✅ PASS" if ok else "❌ FAIL", detail))
        passed += 1 if ok else 0
    print("=" * 62)

    # 溯源信息（不参与计分，缺失只警告）
    if fm:
        ptype = fm.get("persona_type", "?")
        src = fm.get("source_distillate", "?")
        print("  类型: %s · 源档案: %s" % (ptype, src))
        if not fm.get("source_distillate_sha256"):
            print("  ⚠️  缺少 source_distillate_sha256，无法做漂移检测（见 roster-format.md）")
        if ptype == "archetype" and "合成" not in body and "不对应任何具体个人" not in body:
            print("  ⚠️  原型型人格未声明「合成、不对应具体个人」——伦理要求")
    else:
        print("  ⚠️  未解析到 frontmatter")

    print("结果: %d/%d 通过" % (passed, len(checks)))
    if passed == len(checks):
        print("🎉 全部通过。下一步：由独立 agent 跑 references/fidelity-scorecard.md")
        sys.exit(0)
    if passed >= len(checks) - 1:
        print("⚠️  基本通过，建议修复不通过项后交付")
    else:
        print("❌ 多项不通过，建议回到 Phase 2 迭代（迭代上限 2 轮）")
    sys.exit(1)


if __name__ == "__main__":
    main()
