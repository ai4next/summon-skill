#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 运行侧校准（CALIBRATION.md · 本地回路）

管理人格目录下的 `CALIBRATION.md` —— `SKILL.md` 的**运行侧覆盖层**。
这是**本地回路**：使用中暴露的运行侧问题（材料对、表现差）写在这里，**下次触发即生效**，
不需要重铸。（材料侧问题走 `FEEDBACK.jsonl`，那是**给用户的出口**。）

canonical source：`references/calibration.md`。

用法:
    python3 calibrate.py add    --persona-dir DIR --trigger "<触发条件>" \\
                                --action "<收窄动作>" --source "<FEEDBACK 条目/证据指针>" [--force]
    python3 calibrate.py revoke --persona-dir DIR --index N --reason "<撤销理由>"
    python3 calibrate.py list   --persona-dir DIR
    python3 calibrate.py -h | --help        （可放在任意位置）

子命令:
    add      向「生效中」表追加一行（超限 / 重复触发 / 无来源一律拒绝）
    revoke   把第 N 行从「生效中」移入「已撤销」，保留历史与理由，**永不删除**
    list     打印 生效中 / 已撤销 / 待观察 计数与「生效中」各行

⚠️ 最重要的约束：只许收窄，不许放宽（calibration.md §二）
================================================================
**收窄测试（唯一判据）**：
    「这条校准让这个人在更多问题上说话，还是在更少问题上说话？」
    **更多 → 越界，驳回。更少 → 合法。**
================================================================

**诚实声明**：本脚本**无法机械验证**一条校准到底是在收窄还是在放宽——
「更多 / 更少」是对行为语义的判断，没有可用的机械判据。
所以本脚本只做四件事：强制 `--source`（公理 2：无出处的校准 = 意见）、
强制 ≤10 条上限、拒绝同触发条件的重复条目、保留撤销历史。
**收窄与否由人裁决**（`calibration.md` §二 + §六「条目须用户确认才生效」）。
每次 add 后请自行跑一遍上面的收窄测试。

硬性规则（本脚本强制）:
    1. 归属白名单：目录名须以 `-persona` 结尾、含 `SKILL.md`，且不含源材料文件
       （`MATERIAL.md` / `manifest.json` / `QUALITY.md`——见 roster-format.md §一）
    2. `--source` 必须是**非空字符串**（公理 2：无出处的校准，违反 axiom 2）
    3. 「生效中」≤ 10 条；第 11 条**拒绝**并提示重铸（calibration.md §五）
    4. 同触发条件的「生效中」条目已存在 → **拒绝**（本脚本不做覆盖更新；先 revoke 或改写触发条件）
    5. 撤销**只移动、不删除**，历史与理由永久保留
    6. 校准**不改材料哈希**，也**不改四轴分数**（它是运行侧收窄，不是重铸）
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _yaml_subset import (parse_frontmatter, parse_scalar, strip_quotes,
                          as_list, as_str, as_int, as_dict, is_null,
                          sha256_file, read_text, section)
from _material import (FIELD_SHA256, FIELD_SOURCE, FIELD_VERSION, MATERIAL_MARKERS,
                       SOURCE_DIR_DEFAULT, material_path as resolve_material_path)

import argparse
import re
from datetime import date

USAGE = ("用法: python3 calibrate.py {add|revoke|list} --persona-dir DIR [...]\n"
         "  add    --persona-dir DIR --trigger \"<触发条件>\" --action \"<收窄动作>\" "
         "--source \"<FEEDBACK 条目/证据指针>\" [--source-dir DIR] [--force]\n"
         "  revoke --persona-dir DIR --index N --reason \"<撤销理由>\"\n"
         "  list   --persona-dir DIR")

#: calibration.md §五：生效中累计 > 10 条 → 停止追加，该重铸了
ACTIVE_LIMIT = 10

#: 源材料目录标记 —— 出现任一即拒绝（这是材料目录，不是人格目录；见 roster-format.md §一）
SOURCE_MARKERS = MATERIAL_MARKERS

CALIB_FILE = "CALIBRATION.md"

SECTIONS = (("生效中", "active"), ("已撤销", "revoked"), ("待观察", "pending"))

HEADERS = {
    "active": ["#", "触发条件", "校准动作（收窄）", "来源", "生效日期"],
    "revoked": ["#", "原动作", "撤销日期", "撤销理由"],
    "pending": ["#", "现象", "首次出现", "观察结论"],
}


def usage_error(msg):
    sys.stderr.write("❌ " + msg + "\n")
    sys.stderr.write(USAGE + "\n")
    sys.exit(1)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("❌ 参数错误: " + message + "\n")
        sys.stderr.write(USAGE + "\n")
        sys.exit(1)


# --------------------------------------------------------------------------
# 归属白名单（与 feedback_log.py B5 同一套）
# --------------------------------------------------------------------------

def check_persona_dir(pdir):
    if not os.path.isdir(pdir):
        usage_error("人格目录不存在: " + pdir)
    slug = os.path.basename(pdir.rstrip(os.sep))
    if not slug.endswith("-persona"):
        sys.stderr.write("❌ 拒绝: %s\n" % pdir)
        sys.stderr.write("   目录名 `%s` 不以 `-persona` 结尾 —— 这不是本 skill 的人格目录。\n"
                         % slug)
        sys.exit(1)
    for marker in SOURCE_MARKERS:
        if os.path.isfile(os.path.join(pdir, marker)):
            sys.stderr.write("❌ 拒绝: %s\n" % pdir)
            sys.stderr.write("   该目录含 %s，是**源材料目录**，不是人格目录。\n"
                             % marker)
            sys.stderr.write("   归属约束：材料归用户，人格归 summon；summon 只读材料。\n")
            sys.exit(1)
    if not os.path.isfile(os.path.join(pdir, "SKILL.md")):
        sys.stderr.write("❌ 拒绝: %s\n" % pdir)
        sys.stderr.write("   该目录没有 `SKILL.md` —— 人格目录必须含人格本体。\n")
        sys.exit(1)
    return slug


def require_text(args, flag, why):
    v = args.get(flag)
    if v is None:
        usage_error("缺少 %s（%s）" % (flag, why))
    if not isinstance(v, str) or not v.strip():
        usage_error("%s 必须是**非空字符串**（%s）" % (flag, why))
    return v.strip()


# --------------------------------------------------------------------------
# 表格解析 / 渲染 / 拼装
# --------------------------------------------------------------------------

def parse_sections(text):
    """→ dict(active=[cells], revoked=[cells], pending=[cells])。cells 为原始单元格列表。"""
    out = {"active": [], "revoked": [], "pending": []}
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            title = s[3:].strip()
            cur = None
            for name, key in SECTIONS:
                if title.startswith(name):
                    cur = key
                    break
            continue
        if cur is None or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or set(cells[0]) <= set("-: ") or cells[0] == "#":
            continue
        out[cur].append(cells)
    return out


def active_rows(text):
    """→ [(index, [cells...])]，只保留 # 列是整数的行。"""
    out = []
    for cells in parse_sections(text)["active"]:
        n = as_int(cells[0]) if cells else None
        if n is not None:
            out.append((n, cells))
    return out


def render_table(kind, rows):
    head = HEADERS[kind]
    lines = ["| " + " | ".join(head) + " |",
             "|" + "|".join("---" for _ in head) + "|"]
    for cells in rows:
        cells = (list(cells) + [""] * len(head))[:len(head)]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def splice_section(text, title, table_lines):
    """把 `## <title>` 小节里的表格整体换成 table_lines；没有表格则插入。"""
    lines = text.splitlines()
    idx = None
    for k, l in enumerate(lines):
        if l.strip().startswith("## " + title):
            idx = k
            break
    if idx is None:
        lines.extend(["", "## " + title, ""] + table_lines)
        return "\n".join(lines).rstrip("\n") + "\n"

    j = idx + 1
    while j < len(lines) and not lines[j].strip().startswith("|"):
        if lines[j].strip().startswith("## "):
            break
        j += 1
    if j >= len(lines) or not lines[j].strip().startswith("|"):
        at = idx + 1
        while at < len(lines) and not lines[at].strip():
            at += 1
        lines[at:at] = table_lines + [""]
        return "\n".join(lines).rstrip("\n") + "\n"

    k = j
    while k < len(lines) and lines[k].strip().startswith("|"):
        k += 1
    lines[j:k] = table_lines
    return "\n".join(lines).rstrip("\n") + "\n"


def set_meta(text, rounds, today):
    """更新 `**轮次**：N` 与 `**最后更新**：YYYY-MM-DD`；缺失则补一行。"""
    new, n1 = re.subn(r"(\*\*轮次\*\*\s*[:：]\s*)\d+", lambda m: m.group(1) + str(rounds),
                      text, count=1)
    new, n2 = re.subn(r"(\*\*最后更新\*\*\s*[:：]\s*)\d{4}-\d{2}-\d{2}",
                      lambda m: m.group(1) + today, new, count=1)
    if n1 and n2:
        return new
    lines = new.splitlines()
    meta = "**轮次**：%d ｜ **最后更新**：%s" % (rounds, today)
    for anchor in ("**ground truth**", "**人格**", "# 运行侧校准"):
        for k, l in enumerate(lines):
            if l.strip().startswith(anchor):
                at = k + 1
                while at < len(lines) and (lines[at].startswith((" ", "\t", "　"))
                                           or not lines[at].strip()):
                    at += 1
                lines.insert(at, meta)
                return "\n".join(lines).rstrip("\n") + "\n"
    lines.append(meta)
    return "\n".join(lines).rstrip("\n") + "\n"


def get_rounds(text):
    m = re.search(r"\*\*轮次\*\*\s*[:：]\s*(\d+)", text)
    return int(m.group(1)) if m else 0


def norm(s):
    return re.sub(r"\s+", "", s or "")


# --------------------------------------------------------------------------
# 建档（calibration.md §三 模板）
# --------------------------------------------------------------------------

def ground_truth_line(fm, pdir, source_root, slug):
    """按 §三 填 ground truth 行：材料路径 @ sha256 …（version N）。"""
    ax = as_str(fm.get("source_axioms"))
    if ax:
        sha = as_str(fm.get("source_axioms_sha256")) or as_str(
            fm.get(FIELD_SHA256)) or "（未记）"
        return "**ground truth**：%s @ sha256 %s" % (ax, sha)

    src = as_str(fm.get(FIELD_SOURCE)) or slug
    sha = as_str(fm.get(FIELD_SHA256)) or ""
    ver = as_int(fm.get(FIELD_VERSION))
    path = resolve_material_path(source_root, src)
    if path:
        rel = os.path.join(os.path.basename(source_root), src, os.path.basename(path))
        try:
            sha = sha256_file(path)
        except OSError:
            pass
    else:
        # 通用输入：来源可以只是一段描述（口述 / 书名 / 粘贴文本），没有文件
        rel = src
    return "**ground truth**：%s @ sha256 %s%s" % (
        rel, sha or "（未记）", "（version %d）" % ver if ver is not None else "")


def build_template(slug, fm, pdir, source_root, today):
    lines = [
        "# 运行侧校准",
        "",
        "**人格**：%s" % slug,
        ground_truth_line(fm, pdir, source_root, slug),
        "**轮次**：0 ｜ **最后更新**：%s" % today,
        "",
    ]
    for name, key in SECTIONS:
        lines.append("## " + name)
        lines.append("")
        lines.extend(render_table(key, []))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_add(args):
    pdir = os.path.abspath(os.path.expanduser(require_text(args, "--persona-dir", "人格目录")))
    slug = check_persona_dir(pdir)

    trigger = require_text(args, "--trigger", "什么情况下生效；要可判定，不能是「感觉不对时」")
    action = require_text(args, "--action", "具体做什么；且必须是**收窄**动作")
    source = require_text(args, "--source",
                          "公理 2：无出处的校准 = 意见，不得写入（FEEDBACK 条目 / 证据指针）")

    source_root = os.path.abspath(os.path.expanduser(
        args.get("--source-dir") or SOURCE_DIR_DEFAULT))
    today = date.today().isoformat()
    path = os.path.join(pdir, CALIB_FILE)

    if os.path.isfile(path):
        try:
            text = read_text(path)
        except OSError as e:
            usage_error("读取 %s 失败: %s" % (path, e))
    else:
        try:
            fm, _ = parse_frontmatter(read_text(os.path.join(pdir, "SKILL.md")))
        except OSError as e:
            usage_error("读取 SKILL.md 失败: %s" % e)
        fm = as_dict(fm)
        text = build_template(slug, fm, pdir, source_root, today)

    if not re.search(r"^##\s+生效中", text, re.M):
        if not args.get("--force"):
            usage_error("现有 %s 缺 `## 生效中` 小节，结构无法识别 —— 先手工修好，"
                        "或加 --force 追加缺失小节（不会删除任何已有内容）" % CALIB_FILE)
        # 只补缺失的「生效中」；「已撤销 / 待观察」由下方 splice 追加，绝不复位已有内容
        text = splice_section(text, "生效中", render_table("active", []))

    sec = parse_sections(text)
    rows = active_rows(text)

    # 上限（calibration.md §五）
    if len(rows) >= ACTIVE_LIMIT:
        sys.stderr.write("❌ 拒绝追加：「生效中」已有 %d 条，达到上限 %d。\n"
                         % (len(rows), ACTIVE_LIMIT))
        sys.stderr.write("   calibration.md §五：条目累计 > %d 条 → **停止追加**——\n"
                         % ACTIVE_LIMIT)
        sys.stderr.write("   说明根因在档案或人格本身，**该重铸了**，不是继续打补丁。\n")
        sys.stderr.write("   先 revoke 根因已消失的条目，或重铸人格后逐条重判。\n")
        sys.exit(1)

    # 同触发条件 → 拒绝（本脚本不做覆盖更新）
    for n, cells in rows:
        if len(cells) > 1 and norm(cells[1]) == norm(trigger):
            sys.stderr.write("❌ 拒绝追加：「生效中」已存在**同触发条件**的条目 #%d。\n" % n)
            sys.stderr.write("   触发条件：%s\n" % cells[1])
            sys.stderr.write("   本脚本不做覆盖更新。要么先 `revoke --index %d`，"
                             "要么把触发条件改写得可区分。\n" % n)
            sys.exit(1)

    next_n = max([n for n, _ in rows] +
                 [as_int(c[0]) for c in sec["revoked"] if as_int(c[0]) is not None] or [0]) + 1
    new_row = [str(next_n), trigger, action, source, today]

    # 已撤销里的占位行（# 列为「—」）在写入真实记录时清掉
    revoked = [c for c in sec["revoked"] if c and c[0] != "—"]

    text = splice_section(text, "生效中", render_table("active", [c for _, c in rows] + [new_row]))
    text = splice_section(text, "已撤销", render_table("revoked", revoked))
    pending = [c for c in sec["pending"] if as_int(c[0]) is not None]
    text = splice_section(text, "待观察", render_table("pending", pending))
    text = set_meta(text, get_rounds(text) + 1, today)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        usage_error("写入失败: %s" % e)

    print("✅ 已追加校准 #%d: %s" % (next_n, path))
    print("   触发条件: %s" % trigger)
    print("   收窄动作: %s" % action)
    print("   来源: %s（公理 2 要求每条校准可溯源）" % source)
    print("   生效日期: %s · 生效中 %d / %d 条" % (today, len(rows) + 1, ACTIVE_LIMIT))
    print("")
    print("   ⚠️  **收窄测试（请自行裁决，本脚本无法机械验证）**：")
    print("      「这条校准让这个人在更多问题上说话，还是在更少问题上说话？」")
    print("      **更多 → 越界，驳回。更少 → 合法。**")
    print("      放宽必然意味着断言闭包外的内容（公理 2）——那是编造，会判 D。")
    if len(rows) + 1 > ACTIVE_LIMIT - 3:
        print("   ⚠️  生效中已接近 %d 条上限，接近即说明该重铸了。" % ACTIVE_LIMIT)
    print("   ℹ️  校准不改档案哈希，也不改四轴分数；重铸后需逐条重判。")


def cmd_revoke(args):
    pdir = os.path.abspath(os.path.expanduser(require_text(args, "--persona-dir", "人格目录")))
    check_persona_dir(pdir)
    idx = as_int(args.get("--index"))
    if idx is None:
        usage_error("--index 必须是整数（要撤销的「生效中」行号）")
    reason = require_text(args, "--reason", "撤销理由；历史必须保留理由")

    path = os.path.join(pdir, CALIB_FILE)
    if not os.path.isfile(path):
        usage_error("没有 %s —— 无可撤销的校准条目" % path)
    try:
        text = read_text(path)
    except OSError as e:
        usage_error("读取失败: %s" % e)

    sec = parse_sections(text)
    rows = active_rows(text)
    target = [c for n, c in rows if n == idx]
    if not target:
        avail = "、".join("#%d" % n for n, _ in rows) or "（无）"
        usage_error("「生效中」没有 #%d。现有: %s" % (idx, avail))
    target = target[0]
    action = target[2] if len(target) > 2 else ""

    today = date.today().isoformat()
    revoked = [c for c in sec["revoked"] if c and c[0] != "—"]
    revoked.append([str(idx), action, today, reason])

    remaining = [c for n, c in rows if n != idx]
    text = splice_section(text, "生效中", render_table("active", remaining))
    text = splice_section(text, "已撤销", render_table("revoked", revoked))
    pending = [c for c in sec["pending"] if as_int(c[0]) is not None]
    text = splice_section(text, "待观察", render_table("pending", pending))
    text = set_meta(text, get_rounds(text) + 1, today)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        usage_error("写入失败: %s" % e)

    print("✅ 已撤销校准 #%d（移入「已撤销」，历史与理由保留，未删除）" % idx)
    print("   原动作: %s" % action)
    print("   撤销理由: %s" % reason)
    print("   生效中剩余 %d 条 · 已撤销 %d 条" % (len(remaining), len(revoked)))
    print("   ℹ️  若根因是档案已更新，请重铸后逐条重判其余条目（calibration.md §五）。")


def cmd_list(args):
    pdir = os.path.abspath(os.path.expanduser(require_text(args, "--persona-dir", "人格目录")))
    slug = check_persona_dir(pdir)
    path = os.path.join(pdir, CALIB_FILE)

    print("运行侧校准 · %s" % slug)
    if not os.path.isfile(path):
        print("  — 无 %s（运行侧问题出现时用 `calibrate.py add` 建立）" % CALIB_FILE)
        print("  ℹ️  本地回路：失败 → CALIBRATION.md → 下次触发即生效，不需要重铸。")
        return

    try:
        text = read_text(path)
    except OSError as e:
        usage_error("读取失败: %s" % e)

    sec = parse_sections(text)
    rows = active_rows(text)
    revoked = [c for c in sec["revoked"] if c and c[0] != "—"]
    pending = [c for c in sec["pending"] if as_int(c[0]) is not None]

    print("  %s" % path)
    print("  生效中 %d 条 · 已撤销 %d 条 · 待观察 %d 条（生效中上限 %d）"
          % (len(rows), len(revoked), len(pending), ACTIVE_LIMIT))
    if rows:
        print("")
        print("  生效中:")
        for n, c in rows:
            c = (c + [""] * 5)[:5]
            print("    #%s  触发: %s" % (n, c[1] or "—"))
            print("         动作: %s" % (c[2] or "—"))
            print("         来源: %s ｜ 生效: %s" % (c[3] or "—", c[4] or "—"))
    else:
        print("  （生效中为空）")
    if len(rows) > ACTIVE_LIMIT:
        print("")
        print("  ⚠️  生效中超过 %d 条 —— 停止追加：根因在档案或人格本身，该重铸了。"
              % ACTIVE_LIMIT)
    if revoked:
        print("")
        print("  已撤销（历史保留）:")
        for c in revoked:
            c = (c + [""] * 4)[:4]
            print("    #%s  %s ｜ %s ｜ %s" % (c[0], c[1] or "—", c[2] or "—", c[3] or "—"))
    if pending:
        print("")
        print("  待观察:")
        for c in pending:
            c = (c + [""] * 4)[:4]
            print("    #%s  %s ｜ 首次 %s ｜ %s" % (c[0], c[1] or "—", c[2] or "—", c[3] or "—"))
    print("")
    print("  提醒：校准只许**收窄**，不许放宽；每条须带来源，且须用户确认才生效。")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        sys.exit(0)
    if not argv:
        usage_error("缺少子命令")

    parser = _Parser(prog="calibrate.py", add_help=False)
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", add_help=False)
    for f in ("--persona-dir", "--trigger", "--action", "--source", "--source-dir"):
        p_add.add_argument(f, dest=f)
    p_add.add_argument("--force", dest="--force", action="store_true")

    p_rev = sub.add_parser("revoke", add_help=False)
    for f in ("--persona-dir", "--index", "--reason"):
        p_rev.add_argument(f, dest=f)

    p_ls = sub.add_parser("list", add_help=False)
    p_ls.add_argument("--persona-dir", dest="--persona-dir")

    ns = parser.parse_args(argv)
    if ns.cmd not in ("add", "revoke", "list"):
        usage_error("未知子命令: %s（合法: add / revoke / list）" % ns.cmd)

    {"add": cmd_add, "revoke": cmd_revoke, "list": cmd_list}[ns.cmd](vars(ns))


if __name__ == "__main__":
    main()
