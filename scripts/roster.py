#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 人格名册

扫描已铸造的 persona，打印名册表：类型、保真度、源档案、漂移状态、冲突检测。

用法:
    python3 roster.py [--skills-dir ~/.claude/skills] [--archive-dir distilled]

选项:
    --skills-dir DIR   人格所在目录（默认 ~/.claude/skills）
    --archive-dir DIR  蒸馏档案根目录，用于漂移检测（默认 ./distilled）

只读不写：不修改任何文件。

漂移检测:
    比对人脸 frontmatter 里的 source_distillate_sha256 与源档案 DISTILLATE.md 的
    实际哈希。不一致 = 档案在铸人格之后更新过，人格可能已过时。
"""

import hashlib
import json
import os
import re
import sys
import unicodedata

CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def usage_error(msg):
    print("❌ " + msg)
    print("用法: python3 roster.py [--skills-dir ~/.claude/skills] [--archive-dir distilled]")
    sys.exit(1)


def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def truncate(s, width):
    s = str(s)
    if dw(s) <= width:
        return s
    out, used = "", 0
    for c in s:
        w = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if used + w > width - 1:
            break
        out += c
        used += w
    return out + "…"


def strip_quotes(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_frontmatter(text):
    if not text.lstrip().startswith("---"):
        return None
    start = text.index("---") + 3
    end = text.find("\n---", start)
    if end == -1:
        return None
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
    return data


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def read_fidelity(path):
    """从 FIDELITY.md 抽总分与等级。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, None
    m = re.search(r"总分\s*[:：]\s*(\d+)\s*/\s*100", text)
    if not m:
        return None, None
    score = int(m.group(1))
    g = re.search(r"等级\s*([ABCD])", text)
    if g:
        grade = g.group(1)
    else:
        grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"
    return score, grade


DEFECT_TYPES = ("style_drift", "in_scope_gap", "wrong_stance")
SILENCE_TYPES = ("faithful_silence",)


def count_feedback(path):
    """统计 FEEDBACK.jsonl 的人格缺陷与忠实沉默条数（分开计）。

    忠实沉默是**正确行为**，单独统计，绝不算作缺陷。
    """
    if not os.path.isfile(path):
        return 0, 0
    defects = silences = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    t = json.loads(line).get("failure")
                except ValueError:
                    continue
                if t in DEFECT_TYPES:
                    defects += 1
                elif t in SILENCE_TYPES:
                    silences += 1
    except OSError:
        pass
    return defects, silences


def load_panels(skills_dir):
    """读 ~/.claude/skills/panels/*.panel.md，返回 panel 列表。"""
    pdir = os.path.join(skills_dir, "panels")
    if not os.path.isdir(pdir):
        return []
    out = []
    for name in sorted(os.listdir(pdir)):
        if not name.endswith(".panel.md"):
            continue
        path = os.path.join(pdir, name)
        try:
            with open(path, encoding="utf-8") as f:
                fm = parse_frontmatter(f.read()) or {}
        except OSError:
            fm = {}
        members = fm.get("members", [])
        if isinstance(members, str):
            members = [m.strip() for m in members.strip("[]").split(",") if m.strip()]
        out.append({"file": name, "panel": fm.get("panel", name),
                    "topic": fm.get("topic", ""), "members": members,
                    "source_archive": fm.get("source_archive", "")})
    return out


def main():
    argv = sys.argv[1:]
    skills_dir = os.path.expanduser("~/.claude/skills")
    archive_dir = "distilled"
    i = 0
    while i < len(argv):
        if argv[i] in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        if argv[i] == "--skills-dir" and i + 1 < len(argv):
            skills_dir = os.path.expanduser(argv[i + 1])
            i += 2
        elif argv[i] == "--archive-dir" and i + 1 < len(argv):
            archive_dir = argv[i + 1]
            i += 2
        else:
            usage_error("无法识别的参数: " + argv[i])

    if not os.path.isdir(skills_dir):
        print("❌ 人格目录不存在: %s" % skills_dir)
        print("   用 --skills-dir 指定，或先铸一个人格试试。")
        sys.exit(1)

    archive_root = os.path.abspath(os.path.expanduser(archive_dir))
    rows, trigger_map, feedback_map = [], {}, {}

    for entry in sorted(os.listdir(skills_dir)):
        d = os.path.join(skills_dir, entry)
        if not os.path.isdir(d) or not entry.endswith("-persona"):
            continue
        skill_path = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill_path):
            rows.append((entry, "—", "—", "—", "❌ 缺 SKILL.md", "—", "—"))
            continue
        try:
            with open(skill_path, "r", encoding="utf-8") as f:
                fm = parse_frontmatter(f.read())
        except OSError:
            fm = None
        fm = fm or {}

        raw_slug = fm.get("source_distillate", "")
        slug = "—" if str(raw_slug).lower() in ("null", "none", "~", "") else raw_slug
        ptype = fm.get("persona_type", "?")
        recorded = fm.get("source_distillate_sha256", "")
        if str(recorded).lower() in ("null", "none", "~"):
            recorded = ""

        score, grade = read_fidelity(os.path.join(d, "FIDELITY.md"))
        fid = ("%d/%s" % (score, grade)) if score is not None else "未测"
        status = fm.get("status", "—")

        # 使用反馈统计（缺陷 vs 忠实沉默，分开计）
        fb_defects, fb_silence = count_feedback(os.path.join(d, "FEEDBACK.jsonl"))
        if fb_defects or fb_silence:
            fb = "D%d/S%d" % (fb_defects, fb_silence)
        else:
            fb = "—"
        if fb_defects:
            feedback_map[entry] = (fb_defects, fb_silence)

        # 触发词收集（冲突检测用）
        trig = fm.get("triggers", [])
        if isinstance(trig, str):
            trig = [t.strip() for t in trig.strip("[]").split(",") if t.strip()]
        for t in trig:
            trigger_map.setdefault(t, []).append(entry)

        # 漂移检测：以 DISTILLATE.md 的内容哈希为准
        # （manifest.json 的 distillate_sha256 是同一个值，档案不在本地时用它兜底）
        if slug != "—" and recorded:
            archive = os.path.join(archive_root, slug, "DISTILLATE.md")
            actual = sha256_file(archive) if os.path.isfile(archive) else None
            if actual is None:
                mpath = os.path.join(archive_root, slug, "manifest.json")
                try:
                    with open(mpath, "r", encoding="utf-8") as f:
                        actual = json.load(f).get("distillate_sha256")
                except (OSError, ValueError):
                    actual = None
                if actual:
                    drift = "✅ 同步" if actual == recorded else "⚠️ 档案已更新"
                else:
                    drift = "— 档案不在本地"
            else:
                drift = "✅ 同步" if actual == recorded else "⚠️ 档案已更新"
        elif slug != "—":
            drift = "⚠️ 无哈希"
        elif ptype == "archetype":
            drift = "— 原型型无档案"
        else:
            drift = "—"

        rows.append((entry, ptype, fid, status, slug, drift, fb))

    if not rows:
        print("名册为空：%s 下没有 *-persona 目录。" % skills_dir)
        print("先铸一个人格：python3 scripts/forge_scaffold.py <DISTILLATE.md> --out <人格目录>")
        sys.exit(0)

    W = (24, 11, 8, 7, 14, 15, 8)
    line = "┌" + "┬".join("─" * w for w in W) + "┐"
    sep = "├" + "┼".join("─" * w for w in W) + "┤"
    end = "└" + "┴".join("─" * w for w in W) + "┘"

    def row(cells):
        out = "│"
        for c, w in zip(cells, W):
            s = truncate(c, w - 1)
            pad = w - dw(s) - 1
            out += " " + s + " " * (pad if pad > 0 else 0) + "│"
        return out

    print("人格名册: %s" % skills_dir)
    print(line)
    print(row(("人格 (slug-persona)", "类型", "保真度", "状态", "源档案", "漂移状态", "反馈")))
    print(sep)
    for r in rows:
        print(row(r))
    print(end)
    print("  反馈列 D=人格缺陷数 S=忠实沉默数（S 是正确行为，不是缺陷）")

    # 冲突检测
    problems = []
    src_count = {}
    for r in rows:
        if r[4] != "—":
            src_count.setdefault(r[4], []).append(r[0])
    for slug, users in src_count.items():
        if len(users) > 1:
            problems.append("多个人格共用源档案 `%s`: %s" % (slug, "、".join(users)))
    for t, users in sorted(trigger_map.items()):
        if len(users) > 1:
            problems.append("触发词重叠「%s」: %s（会导致误触发）" % (t, "、".join(users)))
    drifted = [r[0] for r in rows if "档案已更新" in r[5]]
    if drifted:
        problems.append("源档案已更新，人格可能过时（建议重铸）: " + "、".join(drifted))
    unmeasured = [r[0] for r in rows if r[2] == "未测"]
    if unmeasured:
        problems.append("未跑保真度评分卡: " + "、".join(unmeasured))
    low = [r[0] for r in rows if r[2] != "未测" and r[2].endswith(("C", "D"))]
    if low:
        problems.append("保真度低于可用门槛（B/70）: " + "、".join(low))
    stale = [r[0] for r in rows if r[3] == "stale"]
    if stale:
        problems.append("状态为 stale，应重铸或标记 retired: " + "、".join(stale))

    print("")
    if problems:
        for p in problems:
            print("  ⚠️  " + p)
    else:
        print("  ✅ 未检出冲突")

    # ---- 人格组（panel）----
    panels = load_panels(skills_dir)
    if panels:
        existing = {r[0] for r in rows}
        stale_names = {r[0] for r in rows if r[3] == "stale" or r[5].find("档案已更新") >= 0}
        print("")
        print("人格组（panel）")
        print("-" * 62)
        for p in panels:
            print("  %s" % p["panel"])
            print("    议题主题: %s · 源档案: %s" % (p["topic"] or "—", p["source_archive"] or "—"))
            missing = [m for m in p["members"] if m not in existing]
            stale_m = [m for m in p["members"] if m in stale_names]
            print("    成员 %d 个: %s" % (len(p["members"]), "、".join(p["members"]) or "（无）"))
            if missing:
                print("    ❌ 成员缺失: %s（先铸，或从 panel 移除）" % "、".join(missing))
            if stale_m:
                print("    ⚠️  成员源档案已更新: %s（建议重铸后再开圆桌）" % "、".join(stale_m))
            if len(p["members"]) < 2:
                print("    ❌ 成员少于 2 个 —— 圆桌至少要两个人")
            if not missing and not stale_m and len(p["members"]) >= 2:
                print("    ✅ 成员齐备")
        print("")
        print("  提醒：panel 只给**主持人**读，绝不注入人格 prompt（见 panel-format.md）")

    # ---- 反馈提示 ----
    if feedback_map:
        print("")
        print("使用反馈（真缺口）")
        for name, (dfc, sil) in sorted(feedback_map.items(), key=lambda kv: -kv[1][0]):
            print("  %-24s 缺陷 %d 条 · 忠实沉默 %d 条" % (name, dfc, sil))
        print("  下一步：跑 distill 的「补充蒸馏」，distill 会只读汇总这些反馈。")
        print("  注意：反馈文件不改档案哈希，**不会**自动触发上面的漂移检测。")

    print("")
    print("  共 %d 个人格 · 保真度 ≥B 的 %d 个" % (
        len(rows),
        sum(1 for r in rows if r[2] != "未测" and not r[2].endswith(("C", "D")))))


if __name__ == "__main__":
    main()
