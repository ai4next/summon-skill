#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 记录人格使用反馈

把使用中暴露的失败写进**人格自己的目录**（`~/.claude/skills/<slug>-persona/FEEDBACK.jsonl`）。

用法:
    python3 feedback_log.py --persona-dir <人格目录> --failure <类型> \\
        --question "<当时的问题>" --evidence "<证据指针>" [选项]

选项:
    --failure NAME    失败类型，见下表（必填）
    --question TEXT   触发失败的问题（必填）
    --evidence TEXT   **证据指针**：档案条目 / 行号 / 出处（必填）
    --formation NAME  产生该反馈的阵型（默认 review）
    --archive-sha SHA 使用时档案的哈希
    --note TEXT       补充说明

失败类型（两类）:
    人格缺陷（计入汇总）:
      style_drift     表达不像（句式/词汇/节奏偏离表达DNA）
      in_scope_gap    问题在该档案维度范围内，却没答好
      wrong_stance    人格立场与档案 A/B 级条目矛盾（必须附反证指针）
    忠实沉默（**不计入**汇总）:
      faithful_silence  档案已标注该缺口 / 主体主动不公开 → 拒答是正确行为

归属约束（本脚本强制）:
    只写人格目录。若 --persona-dir 指向 distill 的档案目录（含 DISTILLATE.md 或
    manifest.json），脚本会**拒绝写入**——档案归 distill 管，人格归 summon 管。
"""

import json
import os
import sys
from datetime import date

DEFECT_TYPES = ("style_drift", "in_scope_gap", "wrong_stance")
SILENCE_TYPES = ("faithful_silence",)
ALL_TYPES = DEFECT_TYPES + SILENCE_TYPES

FORMATION_HINT = ("单召不记录（主 agent 就是人格，记录=跳出角色）。"
                  "单召的失败请事后复盘时用 --formation review 记录。")


def usage_error(msg):
    print("❌ " + msg)
    print("用法: python3 feedback_log.py --persona-dir <人格目录> --failure <类型> \\")
    print("           --question \"...\" --evidence \"...\" [--formation review]")
    print("失败类型: " + " / ".join(ALL_TYPES))
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if not argv:
        usage_error("缺少参数")
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    args, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                args[argv[i]] = argv[i + 1]
                i += 2
            else:
                args[argv[i]] = True
                i += 1
        else:
            i += 1

    pdir = args.get("--persona-dir")
    if not pdir:
        usage_error("缺少 --persona-dir")
    pdir = os.path.abspath(os.path.expanduser(pdir))

    failure = args.get("--failure")
    if not failure:
        usage_error("缺少 --failure")
    if failure not in ALL_TYPES:
        usage_error("未知失败类型「%s」。合法值: %s" % (failure, " / ".join(ALL_TYPES)))

    question = args.get("--question")
    if not question:
        usage_error("缺少 --question（没有具体问题，反馈无法复核）")

    # 铁律3：无证据指针 = 意见，不是缺陷
    evidence = args.get("--evidence")
    if not evidence:
        usage_error("缺少 --evidence。无证据指针的反馈是**意见**不是缺陷，"
                    "按铁律3 不得据此行动。请指明档案条目/行号/出处。")

    formation = args.get("--formation", "review")
    if formation == "single":
        usage_error("单召阵型不记录。" + FORMATION_HINT)

    # ---- 归属约束：拒绝写进 distill 的地盘 ----
    if not os.path.isdir(pdir):
        usage_error("人格目录不存在: " + pdir)
    for marker in ("DISTILLATE.md", "manifest.json", "QUALITY.md"):
        if os.path.isfile(os.path.join(pdir, marker)):
            print("❌ 拒绝写入: %s" % pdir)
            print("   该目录含 %s，看起来是 **distill 的档案目录**，不是人格目录。" % marker)
            print("   归属约束：档案归 distill 管，人格归 summon 管，任何一方都不写对方的地盘。")
            print("   请把 --persona-dir 指向 ~/.claude/skills/<slug>-persona/。")
            sys.exit(1)

    slug = os.path.basename(pdir.rstrip(os.sep))
    if not slug.endswith("-persona"):
        print("⚠️  目录名不以 -persona 结尾（%s）——确认这是人格目录？" % slug)

    rec = {
        "schema_version": 1,
        "date": date.today().isoformat(),
        "persona": slug,
        "archive_sha256": args.get("--archive-sha") or None,
        "formation": formation,
        "question": question,
        "failure": failure,
        "evidence": evidence,
        "note": args.get("--note") or None,
    }

    path = os.path.join(pdir, "FEEDBACK.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    category = "人格缺陷（计入汇总）" if failure in DEFECT_TYPES else "忠实沉默（不计入汇总）"
    print("✅ 已记录反馈: %s" % path)
    print("   类型: %s —— %s" % (failure, category))
    print("   证据: %s" % evidence)
    if failure in SILENCE_TYPES:
        print("")
        print("   ℹ️  忠实沉默是**正确行为**，不会被算作缺陷。")
        print("      记录它是为了统计频率，不是为了让 distill 去补这个缺口——")
        print("      为刻意沉默的主体编造立场会违反 framework §九 并被评分卡判 0 分。")
    print("")
    print("   下一步：由用户运行 distill 的「补充蒸馏」，distill 会**只读**汇总本文件。")
    print("   （注意：追加本文件不会触发 roster 的漂移检测——那要等 distill 更新档案后。）")


if __name__ == "__main__":
    main()
