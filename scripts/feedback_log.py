#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 记录人格使用反馈（EXPORT 通道）

把使用中暴露的失败写进**人格自己的目录**（`~/.claude/skills/<slug>-persona/FEEDBACK.jsonl`）。
这是**出口**：写给**用户**读，用于判断是否修订源材料、是否重铸。
本 skill **不自动改材料，也不自动重铸**——材料侧的决定权在用户。

用法:
    python3 feedback_log.py --persona-dir <人格目录> --failure <类型> \\
        --question "<当时的问题>" --evidence "<证据指针>" --material-sha <sha> [选项]

选项:
    --persona-dir DIR   人格目录（必填；须以 -persona 结尾且含 SKILL.md）
    --failure NAME      失败类型，见下表（必填）
    --question TEXT     触发失败的问题（必填）
    --evidence TEXT     **证据指针**：材料条目 / 公理条目 / 行号（必填，非空字符串）
    --material-sha SHA  **使用时** ground truth 的哈希，用于判断反馈针对哪一版（必填）
    --context NAME      产生该反馈的上下文：`session` / `review` / `eval`（默认 review）
    --formation NAME    **已弃用**（v3.0.0 删除了阵型层）：`--context` 的旧名，仍可读
    --note TEXT         补充说明
    -h, --help          打印本帮助（可放在任意位置）

失败类型（**三类**，canonical source：`roster-format.md` §5.2 + `design-philosophy.md` §三）:
    人格缺陷（**计入**缺陷汇总）:
      style_drift     表达不像（句式/词汇/节奏偏离表达DNA）
      in_scope_gap    问题在该材料维度范围内，却没答好
      wrong_stance    人格立场与档案 A/B 级条目矛盾（必须附反证指针）
      incoherent      模型之间互相矛盾（同情境下相反判断，且两句都没提对方）
    忠实沉默（**不计入**汇总）:
      faithful_silence  材料已标注该缺口 / 主体主动不公开 → 拒答是正确行为
    规则缺口（**不计入**汇总）:
      policy_gap      本 skill 的**规则不完备**（公理没覆盖的新情形）——
                      它推动**公理体系**演进，不是某个人格需要重铸

字段（v3）:
    记录写入 `"context"`（`session` / `review` / `eval`）。v2 的 `"formation"`
    （阵型）已随阵型层删除；读取旧文件时 `roster.py` 会把 `formation` 当遗留字段忽略。

归属约束（本脚本强制，白名单式）:
    目标必须是**已存在**、目录名以 `-persona` 结尾、且含 `SKILL.md` 的目录；
    同时拒绝任何含源材料文件的目录（`MATERIAL.md` / `manifest.json` / `QUALITY.md`，
    见 roster-format.md §一）。材料归用户，人格归 summon；summon 只读材料。
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _yaml_subset import (parse_frontmatter, parse_scalar, strip_quotes,
                          as_list, as_str, as_int, as_dict, is_null,
                          sha256_file, read_text, section)
from _material import MATERIAL_MARKERS

import argparse
import json
import re
from datetime import date

USAGE = ("用法: python3 feedback_log.py --persona-dir <人格目录> --failure <类型> "
         "--question \"...\" --evidence \"...\" --material-sha <sha> "
         "[--context review] [--note \"...\"]")

DEFECT_TYPES = ("style_drift", "in_scope_gap", "wrong_stance", "incoherent")
SILENCE_TYPES = ("faithful_silence",)
POLICY_TYPES = ("policy_gap",)
ALL_TYPES = DEFECT_TYPES + SILENCE_TYPES + POLICY_TYPES

#: 产生反馈的上下文（v3：阵型层已删除，`formation` 仅作遗留别名）
CONTEXTS = ("session", "review", "eval")

#: 源材料目录标记 —— 出现任一即拒绝写入（这是材料目录，不是人格目录；roster-format.md §一）
SOURCE_MARKERS = MATERIAL_MARKERS

SHA_RE = re.compile(r"^[0-9a-f]{64}$")

LEGACY_CONTEXT_NOTE = ("⚠️  `--formation` 已弃用（v3.0.0 删除了阵型层），"
                       "请改用 `--context`：session / review / eval\n")

#: 需要跟值的选项：裸写（后面没值）必须当场拒绝，绝不能变成 Python `True`
VALUE_FLAGS = ("--persona-dir", "--failure", "--question", "--evidence",
               "--context", "--formation", "--material-sha", "--note")


def usage_error(msg):
    sys.stderr.write("❌ " + msg + "\n")
    sys.stderr.write(USAGE + "\n")
    sys.stderr.write("失败类型: " + " / ".join(ALL_TYPES) + "\n")
    sys.exit(1)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("❌ 参数错误: " + message + "\n")
        sys.stderr.write(USAGE + "\n")
        sys.exit(1)


def precheck_bare_flags(argv):
    """裸写 `--evidence`（后面没值 / 直接接另一个选项）→ 当场拒绝。

    B1/B2/E5/E6 的根因都是「裸 flag 被解析成 `True`」，而 `True` 是 truthy，
    于是「无证据 = 拒绝写入」这条旗舰规则被绕过。
    """
    for i, a in enumerate(argv):
        if a not in VALUE_FLAGS:
            continue
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if nxt is None or nxt.startswith("--"):
            usage_error("`%s` 需要跟一个**非空字符串**值——裸写会被误读为 True" % a)


def require_text(args, flag, why):
    """取一个非空字符串选项；缺失 / 空串 / 非字符串一律 usage_error。"""
    v = args.get(flag)
    if v is None:
        usage_error("缺少 %s（%s）" % (flag, why))
    if not isinstance(v, str) or not v.strip():
        usage_error("%s 必须是**非空字符串**（%s）" % (flag, why))
    return v.strip()


def check_persona_dir(pdir):
    """白名单式归属校验（B5）。通过则返回目录名，否则拒绝。"""
    if not os.path.isdir(pdir):
        usage_error("人格目录不存在: " + pdir)

    slug = os.path.basename(pdir.rstrip(os.sep))
    if not slug.endswith("-persona"):
        sys.stderr.write("❌ 拒绝写入: %s\n" % pdir)
        sys.stderr.write("   目录名 `%s` 不以 `-persona` 结尾 —— 这不是本 skill 的人格目录。\n"
                         % slug)
        sys.stderr.write("   归属约束（白名单）：只写 `~/.claude/skills/<slug>-persona/`。\n")
        sys.exit(1)

    for marker in SOURCE_MARKERS:
        if os.path.isfile(os.path.join(pdir, marker)):
            sys.stderr.write("❌ 拒绝写入: %s\n" % pdir)
            sys.stderr.write("   该目录含 %s，是**源材料目录**，不是人格目录。\n"
                             % marker)
            sys.stderr.write("   归属约束：材料归用户，人格归 summon；"
                             "summon 只读材料，绝不写材料目录。\n")
            sys.exit(1)

    if not os.path.isfile(os.path.join(pdir, "SKILL.md")):
        sys.stderr.write("❌ 拒绝写入: %s\n" % pdir)
        sys.stderr.write("   该目录没有 `SKILL.md` —— 人格目录必须含人格本体。\n")
        sys.stderr.write("   请把 --persona-dir 指向 ~/.claude/skills/<slug>-persona/。\n")
        sys.exit(1)
    return slug


def main():
    argv = sys.argv[1:]
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        sys.exit(0)
    if not argv:
        usage_error("缺少参数")

    precheck_bare_flags(argv)

    parser = _Parser(prog="feedback_log.py", add_help=False)
    for flag in VALUE_FLAGS:
        parser.add_argument(flag, dest=flag)
    ns = parser.parse_args(argv)
    args = vars(ns)

    pdir = os.path.abspath(os.path.expanduser(require_text(args, "--persona-dir", "人格目录")))

    failure = require_text(args, "--failure", "失败类型")
    if failure not in ALL_TYPES:
        usage_error("未知失败类型「%s」。合法值: %s" % (failure, " / ".join(ALL_TYPES)))

    question = require_text(args, "--question", "没有具体问题，反馈无法复核")

    # 铁律：无证据指针 = 意见，不是缺陷（公理 2）
    evidence = require_text(args, "--evidence",
                            "无证据指针的反馈是**意见**不是缺陷，不得据此行动")

    material_sha = args.get("--material-sha")
    if not material_sha or not str(material_sha).strip():
        usage_error("缺少 --material-sha（用于判断这条反馈针对哪一版 ground truth）")
    material_sha = str(material_sha).strip()
    if not SHA_RE.match(material_sha):
        sys.stderr.write("⚠️  --material-sha 不是 64 位十六进制 sha256（%s）—— 仍会写入，"
                         "但漂移比对可能对不上。\n" % material_sha[:12])

    # v3：`--context`；`--formation` 是旧名（阵型层已删除），接受但提示弃用
    legacy_ctx = args.get("--formation")
    if legacy_ctx:
        sys.stderr.write(LEGACY_CONTEXT_NOTE)
    context = args.get("--context") or legacy_ctx or "review"
    if not isinstance(context, str) or not context.strip():
        usage_error("--context 必须是**非空字符串**")
    context = context.strip()
    if context not in CONTEXTS:
        usage_error("未知上下文「%s」。合法值: %s" % (context, " / ".join(CONTEXTS)))

    slug = check_persona_dir(pdir)

    rec = {
        "schema_version": 1,
        "date": date.today().isoformat(),
        "persona": slug,
        "material_sha256": material_sha,
        "context": context,
        "question": question,
        "failure": failure,
        "evidence": evidence,
        "note": (args.get("--note") or None),
    }

    path = os.path.join(pdir, "FEEDBACK.jsonl")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        usage_error("写入失败: %s" % e)

    if failure in DEFECT_TYPES:
        category = "人格缺陷（计入缺陷汇总）"
    elif failure in SILENCE_TYPES:
        category = "忠实沉默（**不计入**汇总）"
    else:
        category = "规则缺口（**不计入**汇总）"

    print("✅ 已记录反馈: %s" % path)
    print("   类型: %s —— %s" % (failure, category))
    print("   上下文: %s · ground truth 哈希: %s" % (context, material_sha[:12]))
    print("   证据: %s" % evidence)

    if failure == "incoherent":
        print("")
        print("   ℹ️  模型互相矛盾是**人格缺陷**（公理 4）：并列摆着的相反判断要修——")
        print("      要么改成显式张力（人格自己承认那个冲突），要么删掉一条。")
    if failure in SILENCE_TYPES:
        print("")
        print("   ℹ️  忠实沉默是**正确行为**，不会被算作缺陷。")
        print("      记录它是为了统计频率，不是为了「补上」这个缺口——")
        print("      为刻意沉默的主体编造立场会违反公理 5，并被评分卡判 0 分。")
    if failure in POLICY_TYPES:
        print("")
        print("   ℹ️  规则缺口**不是人格缺陷**，不会被算作缺陷，也**不驱动重铸**。")
        print("      它记录的是**本 skill 的规则不完备**（公理没覆盖的新情形），")
        print("      用途是推动**公理体系**演进（design-philosophy.md §三）——")
        print("      出现频次高的 policy_gap 说明某条公理需要补射程，而不是某个人格要重铸。")

    print("")
    print("   下一步：由**用户**读本文件，决定是否修订源材料（材料哈希随之改变）。")
    print("   （注意：追加本文件**不会**触发 roster 的漂移检测——那要等材料真的更新后。）")


if __name__ == "__main__":
    main()
