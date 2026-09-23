#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 保真度评测记录与对比

维护 EVALS.jsonl（追加式评测历史），并提供**拒绝过度断言**的版本对比。

背景:
    FIDELITY.md 每次重铸都被覆盖，分数历史随之销毁。EVALS.jsonl 只增不改，
    让「重铸后比上一版好在哪」这个问题第一次变得可回答。

用法:
    python3 eval_record.py record  --file ~/.claude/skills/<slug>-persona/EVALS.jsonl --json '<记录 JSON>'
    python3 eval_record.py record  --file <path> --from-file <json文件>
    python3 eval_record.py history --file <path>
    python3 eval_record.py compare --file <path> [--noise 10]

    scores 的维度用保真度评分卡的六维：
      立场一致性 / 风格辨识度 / 边缘诚实度 / 来源透明度 / 结构完整度 / 档案一致性

对比的有效性检查（关键）:
    compare **拒绝**在下列情况下给出趋势结论，只如实说明原因：
      1. 题目集变了（含题目退役）—— 超范围题在领域被覆盖后失效，
         直接比会得出「越完整分越低」的假退步
      2. 评分 agent < 2 个 —— 单次 LLM 评分噪声 ±5-10 分，不足以支撑趋势
      3. 分数差落在噪声带内 —— 分不出是真变化还是抖动
      4. 两次评的是同一个 artifact_sha256 —— 没有变化可比

只读不写（record 除外，它只追加）。
"""

import json
import os
import sys
import unicodedata
from datetime import datetime, timezone

NOISE_BAND = 10  # 与两份评分卡的「分差>10分需复核」保持一致


def usage_error(msg):
    print("❌ " + msg)
    print("用法: python3 eval_record.py {record|history|compare} --file <EVALS.jsonl> [--json ...]")
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


def load(path):
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                print("⚠️  第 %d 行 JSON 解析失败，跳过: %s" % (n, e))
    return out


def q_sig(rec):
    """题目集签名：id + status。任何变化都意味着两次评测不可直接比较。"""
    return tuple(sorted((q.get("id"), q.get("status")) for q in rec.get("questions", [])))


def cmd_record(args):
    path = args.get("--file")
    if not path:
        usage_error("record 需要 --file")

    raw = args.get("--json")
    if not raw and args.get("--from-file"):
        try:
            raw = open(args["--from-file"], encoding="utf-8").read()
        except OSError as e:
            usage_error("读取失败: %s" % e)
    if not raw:
        usage_error("record 需要 --json 或 --from-file")

    try:
        rec = json.loads(raw)
    except ValueError as e:
        usage_error("记录不是合法 JSON: %s" % e)

    missing = [k for k in ("version", "artifact_sha256", "models", "scorers", "scores", "total")
               if k not in rec]
    if missing:
        usage_error("记录缺少必填字段: " + "、".join(missing))
    if not isinstance(rec.get("models"), dict) or "score" not in rec["models"]:
        usage_error("models 必须是含 answer/score 的对象（评分必须独立于答题）")
    if not rec.get("questions"):
        print("⚠️  记录未内嵌题目集（questions）—— compare 将无法判断可比性")

    rec.setdefault("schema_version", 1)
    rec.setdefault("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    rec.setdefault("run_id", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("✅ 已追加评测记录: %s" % path)
    print("   version=%s total=%s grade=%s scorers=%s"
          % (rec.get("version"), rec.get("total"), rec.get("grade", "—"), rec.get("scorers")))
    if rec.get("scorers", 0) < 2:
        print("   ⚠️  评分 agent 仅 %s 个 —— compare 不会给出趋势结论（噪声大于信号）"
              % rec.get("scorers"))


def cmd_history(args):
    path = args.get("--file")
    if not path:
        usage_error("history 需要 --file")
    recs = load(path)
    if not recs:
        print("（无评测记录: %s）" % path)
        return

    dims = []
    for r in recs:
        for d in (r.get("scores") or {}):
            if d not in dims:
                dims.append(d)

    W = [8, 12, 8, 8] + [max(8, dw(d) + 2) for d in dims]
    line = "┌" + "┬".join("─" * w for w in W) + "┐"
    sep = "├" + "┼".join("─" * w for w in W) + "┤"
    end = "└" + "┴".join("─" * w for w in W) + "┘"

    def row(cells):
        o = "│"
        for c, w in zip(cells, W):
            s = truncate(c, w - 1)
            pad = w - dw(s) - 1
            o += " " + s + " " * (pad if pad > 0 else 0) + "│"
        return o

    print("评测历史: %s（%d 次）" % (path, len(recs)))
    print(line)
    print(row(["ver", "date", "total", "grade"] + dims))
    print(sep)
    for r in recs:
        sc = r.get("scores") or {}
        print(row([r.get("version", "?"), r.get("date", "?"), r.get("total", "?"),
                   r.get("grade", "—")] + [sc.get(d, "—") for d in dims]))
    print(end)


def cmd_compare(args):
    path = args.get("--file")
    if not path:
        usage_error("compare 需要 --file")
    try:
        noise = int(args.get("--noise", NOISE_BAND))
    except ValueError:
        usage_error("--noise 必须是整数")

    recs = load(path)
    if len(recs) < 2:
        print("⚠️  只有 %d 次记录，无法对比。至少需要 2 次。" % len(recs))
        return

    prev, cur = recs[-2], recs[-1]
    print("对比: version %s → %s" % (prev.get("version"), cur.get("version")))
    print("=" * 62)

    # ---- 有效性检查（这是本命令的核心价值：拒绝过度断言） ----
    blockers = []

    if prev.get("artifact_sha256") == cur.get("artifact_sha256"):
        blockers.append("两次评的是**同一个**档案版本（artifact_sha256 相同）——没有变化可比")

    sp, sc_ = q_sig(prev), q_sig(cur)
    if sp != sc_:
        pp = {q.get("id"): q.get("status") for q in prev.get("questions", [])}
        cc = {q.get("id"): q.get("status") for q in cur.get("questions", [])}
        retired = [i for i in pp if i not in cc or cc[i] == "retired"]
        added = [i for i in cc if i not in pp]
        detail = []
        if retired:
            detail.append("退役 %d 题（%s）" % (len(retired), "、".join(retired[:3])))
        if added:
            detail.append("新增 %d 题（%s）" % (len(added), "、".join(added[:3])))
        if not detail:
            detail.append("题目状态有变动")
        blockers.append("题目集已变化：" + "，".join(detail) +
                        "\n      缺口被补上后原题失效，直接比会得出「越完整分越低」的假退步")

    if min(prev.get("scorers", 1), cur.get("scorers", 1)) < 2:
        blockers.append("评分 agent 少于 2 个（%s / %s）—— 单次 LLM 评分噪声 ±5-10 分，"
                        "不足以支撑趋势结论" % (prev.get("scorers"), cur.get("scorers")))

    # 逐维 delta
    dims = [d for d in (cur.get("scores") or {}) if d in (prev.get("scores") or {})]
    deltas = {d: cur["scores"][d] - prev["scores"][d] for d in dims}
    total_delta = (cur.get("total") or 0) - (prev.get("total") or 0)

    W = [22, 8, 8, 8]
    line = "┌" + "┬".join("─" * w for w in W) + "┐"
    sep = "├" + "┼".join("─" * w for w in W) + "┤"
    end = "└" + "┴".join("─" * w for w in W) + "┘"

    def row(cells):
        o = "│"
        for c, w in zip(cells, W):
            s = truncate(c, w - 1)
            pad = w - dw(s) - 1
            o += " " + s + " " * (pad if pad > 0 else 0) + "│"
        return o

    print(line)
    print(row(("维度", "上版", "本版", "Δ")))
    print(sep)
    for d in dims:
        dv = deltas[d]
        print(row((d, prev["scores"][d], cur["scores"][d], ("%+d" % dv) if dv else "0")))
    print(sep)
    print(row(("总分", prev.get("total"), cur.get("total"), "%+d" % total_delta)))
    print(end)

    # ---- 结论 ----
    print("")
    if blockers:
        print("❌ 本次对比不构成有效对比：")
        for b in blockers:
            print("   - " + b)
        print("")
        print("   建议：修好上述问题后再比，或把它当作一次独立的分数记录（history 里仍可见）。")
        return

    if abs(total_delta) <= noise:
        print("⚠️  总分变化 %+d，落在噪声带（±%d）内 —— 分不出是真变化还是抖动。" % (total_delta, noise))
        print("   建议：加跑第二个评分 agent，看分差是否稳定。")
        return

    verdict = "提升" if total_delta > 0 else "退步"
    print("✅ 对比有效：总分 %+d，判定为**%s**。" % (total_delta, verdict))
    ups = [d for d in dims if deltas[d] > 0]
    downs = [d for d in dims if deltas[d] < 0]
    if ups:
        print("   上升维度: " + "、".join("%s %+d" % (d, deltas[d]) for d in ups))
    if downs:
        print("   下降维度: " + "、".join("%s %+d" % (d, deltas[d]) for d in downs))
    if verdict == "提升":
        print("   下一步：把这版设为新基线，继续下一次迭代。")


def main():
    argv = sys.argv[1:]
    if not argv:
        usage_error("缺少子命令")
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd = argv[0]
    if cmd not in ("record", "history", "compare"):
        usage_error("未知子命令: " + cmd)

    args, i = {}, 1
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                args[key] = argv[i + 1]
                i += 2
            else:
                args[key] = True
                i += 1
        else:
            i += 1

    {"record": cmd_record, "history": cmd_history, "compare": cmd_compare}[cmd](args)


if __name__ == "__main__":
    main()
