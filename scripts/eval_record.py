#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 质检评测记录与对比（四轴分开报）

维护 `EVALS.jsonl`（追加式评测历史），并提供**拒绝过度断言**的版本对比。

背景:
    `FIDELITY.md` 每次重铸都被覆盖，分数历史随之销毁。`EVALS.jsonl` 只增不改，
    让「重铸后比上一版好在哪」这个问题第一次变得可回答。

用法:
    python3 eval_record.py record  --file <EVALS.jsonl> --json '<记录 JSON>'
    python3 eval_record.py record  --file <EVALS.jsonl> --from-file <json文件>
    python3 eval_record.py history --file <EVALS.jsonl>
    python3 eval_record.py compare --file <EVALS.jsonl> [--noise 10]
    python3 eval_record.py -h | --help        （可放在任意位置）

子命令:
    record    追加一条评测记录（只追加，不改历史行）
    history   打印评测历史（**四轴各一列**）
    compare   对比最近两次，拒绝过度断言（四轴分开比）

记录必填字段（`roster-format.md` §5.3 + SKILL.md P6 + `fidelity-scorecard.md`）:
    version / artifact_sha256 / models / scorers / questions（非空）/
    axes（四轴）或旧格式 `fidelity` / total

    `models` 必须**同时**含 `answer` 与 `score` 两个模型 —— 答题与评分必须独立，
    绝不自评自证。

四轴（`fidelity-scorecard.md` §零）:
    生成力 G（/30）· 自洽性 C（/25）· 辨识度 D（/20）· 溯源 S（/25）。
    **四个数分开记、分开报、绝不相加**（公理 3）——合并立刻制造刷分路径。
    `record` 优先读顶层 `axes`（`{"生成力": N, "自洽性": N, "辨识度": N, "溯源": N}`
    + `total` / `grade` / `mode`）；旧记录的 `fidelity` / `scores` 形状在读取时仍被接受。

对比的有效性检查（关键）:
    compare **拒绝**在下列情况下给出趋势结论，只如实说明原因：
      1. 任一记录**缺题目集或题目集为空** —— 无法判断两次评测是否可比（**本次对比无效**）
      2. 题目集变了（含题目退役）—— 超范围题在领域被覆盖后失效，
         直接比会得出「越完整分越低」的假退步
      3. 评分 agent < 2 个 —— 单次 LLM 评分噪声 ±5-10 分，不足以支撑趋势
      4. 总分差落在噪声带内 —— 分不出是真变化还是抖动
      5. 两次评的是同一个 artifact_sha256 —— 没有变化可比
    四轴未测（旧记录）时**不画轴趋势**，如实说明。

退出码:
    0  成功（compare 给出了有效趋势结论）
    1  用法错误（stderr）
    2  **compare 拒绝给出趋势结论**（本次对比无效 / 噪声带内 / 记录不足）——
       调用方据此判断「不要据此下结论」

只读不写（record 除外，它只追加）。
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _yaml_subset import (parse_frontmatter, parse_scalar, strip_quotes,
                          as_list, as_str, as_int, as_dict, is_null,
                          sha256_file, read_text, section)

import argparse
import json
import unicodedata
from datetime import datetime, timezone

USAGE = ("用法: python3 eval_record.py {record|history|compare} --file <EVALS.jsonl> "
         "[--json '<JSON>'] [--from-file <文件>] [--noise 10]")

NOISE_BAND = 10   # 与评分卡「分差 >10 分需复核」保持一致
TOTAL_THRESHOLD = 70

#: 四轴（名称, 满分）——顺序即报表顺序（`fidelity-scorecard.md` §零）
AXES = (("生成力", 30), ("自洽性", 25), ("辨识度", 20), ("溯源", 25))
AXIS_NAMES = tuple(n for n, _ in AXES)
AXIS_MAX = dict(AXES)

#: 分轴红线（§五）：S=0 直接判 D；C<15 / D<12 最高判 C；G<12 标复读机
AXIS_REDLINE = {"生成力": 12, "自洽性": 15, "辨识度": 12, "溯源": 0}

#: 需要跟值的选项：裸写（后面没值）必须当场拒绝，绝不能变成 Python `True`
VALUE_FLAGS = ("--file", "--json", "--from-file", "--noise")

EXIT_REFUSED = 2


def usage_error(msg):
    sys.stderr.write("❌ " + msg + "\n")
    sys.stderr.write(USAGE + "\n")
    sys.exit(1)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write("❌ 参数错误: " + message + "\n")
        sys.stderr.write(USAGE + "\n")
        sys.exit(1)


def precheck_bare_flags(argv):
    for i, a in enumerate(argv):
        if a not in VALUE_FLAGS:
            continue
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if nxt is None or nxt.startswith("--"):
            usage_error("`%s` 需要跟一个**非空字符串**值——裸写会被误读为 True" % a)


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


def table(head, rows):
    W = [max(8, dw(h) + 2) for h in head]
    for r in rows:
        for i, c in enumerate(r):
            W[i] = max(W[i], min(dw(c) + 2, 40))
    line = "┌" + "┬".join("─" * w for w in W) + "┐"
    sep = "├" + "┼".join("─" * w for w in W) + "┤"
    end = "└" + "┴".join("─" * w for w in W) + "┘"
    out = [line, _row(head, W), sep]
    for r in rows:
        out.append(_row(r, W))
    out.append(end)
    return "\n".join(out)


def _row(cells, W):
    o = "│"
    for c, w in zip(cells, W):
        s = truncate(c, w - 1)
        pad = w - dw(s) - 1
        o += " " + s + " " * (pad if pad > 0 else 0) + "│"
    return o


# --------------------------------------------------------------------------
# 读 / 归一化（E1-E3：类型与坏行都在这里被驯服）
# --------------------------------------------------------------------------

def load(path):
    """读 EVALS.jsonl；非 dict 的合法 JSON 行跳过并告警（E3）。"""
    if not os.path.isfile(path):
        return []
    out = []
    try:
        f = open(path, encoding="utf-8")
    except OSError as e:
        usage_error("读取失败: %s" % e)
    with f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError as e:
                print("⚠️  第 %d 行 JSON 解析失败，跳过: %s" % (n, e))
                continue
            if not isinstance(rec, dict):   # E3：`123` / `[]` 是合法 JSON 但不是记录
                print("⚠️  第 %d 行不是 JSON 对象（%s），跳过" % (n, type(rec).__name__))
                continue
            out.append(rec)
    return out


def get_axes(rec):
    """→ {轴: int}。优先顶层 `axes`，其次 `fidelity.axes`；旧记录回落同名维度键。

    四个轴**分开取、分开存**——本函数绝不把任何两个轴相加（公理 3）。
    """
    out = {}
    for src in (as_dict(rec.get("axes")),
                as_dict(as_dict(rec.get("fidelity")).get("axes"))):
        for k, v in src.items():
            n = as_int(v)
            if n is not None and str(k) in AXIS_MAX:
                out.setdefault(str(k), n)
    if out:
        return out
    # 迁移期旧记录：六维 `scores` 里若出现四轴同名键，照样读出（不猜、不映射）
    for src in (as_dict(rec.get("scores")),
                as_dict(as_dict(rec.get("fidelity")).get("scores"))):
        for k, v in src.items():
            n = as_int(v)
            if n is not None and str(k) in AXIS_MAX:
                out.setdefault(str(k), n)
    return out


def get_total(rec):
    t = as_int(rec.get("total"))
    if t is None:
        t = as_int(as_dict(rec.get("fidelity")).get("total"))
    return t


def get_grade(rec):
    g = as_str(rec.get("grade"))
    if g is None:
        g = as_str(as_dict(rec.get("fidelity")).get("grade"))
    return g


def get_mode(rec):
    m = as_str(rec.get("mode"))
    if m is None:
        m = as_str(as_dict(rec.get("fidelity")).get("mode"))
    return m


def grade_of(score):
    return "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"


def get_scorers(rec):
    """E1：`scorers` 可能是字符串（如 "2"）——统一 as_int，比较/运算不再崩。"""
    return as_int(rec.get("scorers"))


def q_sig(rec):
    """题目集签名：id + status。任何变化都意味着两次评测不可直接比较。"""
    out = []
    for q in as_list(rec.get("questions")):
        if isinstance(q, dict):
            out.append((as_str(q.get("id")), as_str(q.get("status"))))
    return tuple(sorted(out))


def q_detail(rec):
    return {as_str(q.get("id")): as_str(q.get("status"))
            for q in as_list(rec.get("questions")) if isinstance(q, dict)}


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------

def cmd_record(args):
    path = args.get("--file")
    if not isinstance(path, str) or not path.strip():
        usage_error("record 需要 --file（EVALS.jsonl 路径）")
    path = path.strip()

    raw = args.get("--json")
    if raw is not None and not isinstance(raw, str):
        usage_error("--json 必须是**字符串**")     # E6
    if not raw and args.get("--from-file"):
        try:
            raw = read_text(args["--from-file"])
        except OSError as e:
            usage_error("读取失败: %s" % e)
    if not raw:
        usage_error("record 需要 --json 或 --from-file")

    try:
        rec = json.loads(raw)
    except ValueError as e:
        usage_error("记录不是合法 JSON: %s" % e)
    if not isinstance(rec, dict):
        usage_error("记录必须是 JSON **对象**（当前是 %s）" % type(rec).__name__)

    missing = [k for k in ("version", "artifact_sha256", "models", "scorers")
               if k not in rec]
    if missing:
        usage_error("记录缺少必填字段: " + "、".join(missing))

    if as_int(rec.get("version")) is None:
        usage_error("`version` 必须是整数（档案版本）")
    if not as_str(rec.get("artifact_sha256")):
        usage_error("`artifact_sha256` 必须是非空字符串（两次对比的同一性依据）")

    # E7：答题与评分必须独立 —— answer 与 score 都要有
    models = rec.get("models")
    if not isinstance(models, dict):
        usage_error("`models` 必须是对象（含 answer 与 score 两个模型）")
    bad_models = [k for k in ("answer", "score") if not as_str(models.get(k))]
    if bad_models:
        usage_error("`models` 缺少 %s —— 答题与评分必须是**两个独立** agent，绝不自评自证"
                    % "、".join(bad_models))

    # E1/E2：scorers 与 total 必须是数字
    scorers = as_int(rec.get("scorers"))
    if scorers is None:
        usage_error("`scorers` 必须是整数（评分 agent 个数；字符串数字也会被拒绝）")
    if scorers < 1:
        usage_error("`scorers` 至少为 1")

    total = get_total(rec)
    if total is None:
        usage_error("记录缺少质检总分：需要顶层 `total` 或 `fidelity.total`")
    if not (0 <= total <= 100):
        usage_error("质检总分必须在 0-100（当前 %s）" % total)

    # v3：优先 `axes`（四轴）；旧记录仍接受 `fidelity` / `scores` 形状
    axes_raw = as_dict(rec.get("axes")) or as_dict(as_dict(rec.get("fidelity")).get("axes"))
    legacy_scores = (as_dict(rec.get("scores"))
                     or as_dict(as_dict(rec.get("fidelity")).get("scores")))
    if axes_raw:
        lack = [n for n in AXIS_NAMES if as_int(axes_raw.get(n)) is None]
        if lack:
            usage_error("`axes` 缺轴：%s —— 四轴必须齐（生成力/自洽性/辨识度/溯源）"
                        % "、".join(lack))
        for n, mx in AXES:
            v = as_int(axes_raw.get(n))
            if not (0 <= v <= mx):
                usage_error("`axes.%s` 必须在 0-%d（当前 %s）" % (n, mx, v))
    elif legacy_scores:
        print("⚠️  记录用的是旧格式 `fidelity` / `scores` —— 已接受，但请改用四轴 `axes`"
              "（生成力/自洽性/辨识度/溯源）")
    else:
        usage_error("记录缺少四轴：需要顶层 `axes` = {\"生成力\": N, \"自洽性\": N, "
                    "\"辨识度\": N, \"溯源\": N}（旧格式 `fidelity.scores` 亦被接受）")

    mode = get_mode(rec)
    if mode is not None and mode.lower() not in ("full", "lite"):
        usage_error("`mode` 只能是 full 或 lite（当前 %r）" % mode)
    if get_grade(rec) is None:
        rec["grade"] = grade_of(total)

    # E4：record 必须带**非空**题目集
    questions = rec.get("questions")
    if not isinstance(questions, list) or not questions:
        usage_error("记录必须有**非空** `questions` 数组（题目内嵌在记录里，不做全局题库）。"
                    "缺题目集时 compare 无法判断两次评测是否可比 → 会拒绝给趋势结论")
    bad_q = [i for i, q in enumerate(questions, 1) if not isinstance(q, dict)]
    if bad_q:
        usage_error("`questions` 第 %s 项不是对象" % "、".join(map(str, bad_q)))
    no_id = [str(i) for i, q in enumerate(questions, 1) if not as_str(q.get("id"))]
    if no_id:
        print("⚠️  题目第 %s 项缺 `id` —— compare 的题目集签名会退化" % "、".join(no_id))

    rec.setdefault("schema_version", 1)
    rec.setdefault("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    rec.setdefault("run_id", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        usage_error("写入失败: %s" % e)

    axes = get_axes(rec)
    axis_txt = " · ".join("%s %s/%d" % (n, axes.get(n, "—"), mx) for n, mx in AXES)
    print("✅ 已追加评测记录: %s" % path)
    print("   version=%s · 总分 %s/100 (%s) · mode %s · scorers=%s"
          % (as_int(rec.get("version")), total, get_grade(rec) or "—",
             mode or "未标", scorers))
    print("   四轴分开记：%s" % axis_txt)
    print("   **四个数不相加、不互相补偿**（design-philosophy.md 公理 3）")
    if scorers < 2:
        print("   ⚠️  评分 agent 仅 %d 个 —— compare 不会给出趋势结论（噪声大于信号）"
              % scorers)


# --------------------------------------------------------------------------
# history
# --------------------------------------------------------------------------

def cmd_history(args):
    path = args.get("--file")
    if not isinstance(path, str) or not path.strip():
        usage_error("history 需要 --file")
    path = path.strip()
    recs = load(path)
    if not recs:
        print("（无评测记录: %s）" % path)
        return

    head = ["ver", "date", "总分/100", "grade", "mode"] + \
           ["%s/%d" % (n, mx) for n, mx in AXES]
    rows, legacy = [], []
    for r in recs:
        total = get_total(r)
        axes = get_axes(r)
        if not any(n in axes for n in AXIS_NAMES):
            legacy.append(str(as_int(r.get("version"), "?")))
        rows.append([as_int(r.get("version"), "?"), as_str(r.get("date"), "?"),
                     total if total is not None else "—", get_grade(r) or "—",
                     get_mode(r) or "未标"]
                    + [axes.get(n, "—") for n, _ in AXES])
    print("评测历史: %s（%d 次）" % (path, len(recs)))
    print(table(head, rows))
    print("  四轴：生成力/30 · 自洽性/25 · 辨识度/20 · 溯源/25 —— **四个数分开报、绝不相加**"
          "（公理 3）")
    print("  门槛：总分 ≥%d 为 B；分轴红线：溯源 S=0 → 判 D · 自洽性 C<15 / 辨识度 D<12 → "
          "最高判 C · 生成力 G<%d → 复读机" % (TOTAL_THRESHOLD, AXIS_REDLINE["生成力"]))
    if legacy:
        print("  ⚠️  旧格式（无四轴，只报总分）: %s —— 四轴未测，不得声称四轴达标"
              % "、".join(legacy))


# --------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------

def cmd_compare(args):
    path = args.get("--file")
    if not isinstance(path, str) or not path.strip():
        usage_error("compare 需要 --file")
    path = path.strip()

    noise = args.get("--noise")
    if noise is None:
        noise = NOISE_BAND
    elif not isinstance(noise, str):
        usage_error("--noise 必须是整数字符串")      # E5
    else:
        try:
            noise = int(noise.strip())
        except ValueError:
            usage_error("--noise 必须是整数")
    if noise < 0:
        usage_error("--noise 不能为负")

    recs = load(path)
    if len(recs) < 2:
        print("❌ 本次对比无效：只有 %d 次记录，至少需要 2 次。" % len(recs))
        sys.exit(EXIT_REFUSED)

    prev, cur = recs[-2], recs[-1]
    print("对比: version %s → %s" % (as_int(prev.get("version"), "?"),
                                     as_int(cur.get("version"), "?")))
    print("=" * 62)

    total_prev, total_cur = get_total(prev), get_total(cur)
    grade_prev, grade_cur = get_grade(prev), get_grade(cur)
    axes_prev, axes_cur = get_axes(prev), get_axes(cur)
    s_prev, s_cur = get_scorers(prev), get_scorers(cur)

    # ---- 有效性检查（本命令的核心价值：拒绝过度断言）----
    blockers = []

    sp, sc_ = q_sig(prev), q_sig(cur)
    if not sp or not sc_:                              # E4
        who = []
        if not sp:
            who.append("上版")
        if not sc_:
            who.append("本版")
        blockers.append("%s**缺题目集或题目集为空** —— 无法判断两次评测是否可比"
                        "（缺题目集时任何分数差都不可解释）" % "、".join(who))
    elif sp != sc_:
        pp, cc = q_detail(prev), q_detail(cur)
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

    if prev.get("artifact_sha256") == cur.get("artifact_sha256"):
        blockers.append("两次评的是**同一个**档案版本（artifact_sha256 相同）——没有变化可比")

    if min(s_prev if s_prev is not None else 1,
           s_cur if s_cur is not None else 1) < 2:
        blockers.append("评分 agent 少于 2 个（%s / %s）—— 单次 LLM 评分噪声 ±5-10 分，"
                        "不足以支撑趋势结论" % (s_prev, s_cur))

    if total_prev is None or total_cur is None:
        blockers.append("缺少质检总分 —— 无法算总分趋势")

    total_delta = (total_cur - total_prev
                   if (total_prev is not None and total_cur is not None) else None)

    # ---- 四轴分开画（绝不相加）----
    axis_rows = []
    for n, mx in AXES:
        a, b = axes_prev.get(n), axes_cur.get(n)
        d = ("%+d" % (b - a)) if (a is not None and b is not None) else "不画趋势"
        axis_rows.append(["%s/%d" % (n, mx), a if a is not None else "未测",
                          b if b is not None else "未测", d])
    axis_rows.append(["总分/100", total_prev if total_prev is not None else "—",
                      total_cur if total_cur is not None else "—",
                      ("%+d" % total_delta) if total_delta is not None else "—"])
    print("")
    print(table(["轴", "上版", "本版", "Δ"], axis_rows))
    print("  注：四轴是四根独立的轴，**不相加、不互相补偿**（公理 3）；"
          "总分是评分卡给出的数，不是脚本加出来的。")

    # ---- 分轴红线（§五）----
    redlines = []
    if axes_cur:
        if axes_cur.get("溯源") == 0:
            redlines.append("本版 溯源 S=0 → **直接判 D**，不论总分")
        if axes_cur.get("自洽性", 99) < AXIS_REDLINE["自洽性"]:
            redlines.append("本版 自洽性 C=%s < %d → 最高判 C"
                            % (axes_cur.get("自洽性"), AXIS_REDLINE["自洽性"]))
        if axes_cur.get("辨识度", 99) < AXIS_REDLINE["辨识度"]:
            redlines.append("本版 辨识度 D=%s < %d → 最高判 C"
                            % (axes_cur.get("辨识度"), AXIS_REDLINE["辨识度"]))
        if axes_cur.get("生成力", 99) < AXIS_REDLINE["生成力"]:
            redlines.append("本版 生成力 G=%s < %d → 标「复读机」"
                            % (axes_cur.get("生成力"), AXIS_REDLINE["生成力"]))
    if redlines:
        print("")
        print("⚠️  分轴红线（总分达标也一票否决）：")
        for x in redlines:
            print("   - " + x)

    print("")
    if blockers:
        print("❌ 本次对比不构成有效对比：")
        for b in blockers:
            print("   - " + b)
        print("")
        print("   建议：修好上述问题后再比，或把它当作一次独立的分数记录（history 里仍可见）。")
        sys.exit(EXIT_REFUSED)

    if abs(total_delta) <= noise:
        print("⚠️  总分变化 %+d，落在噪声带（±%d）内 —— 分不出是真变化还是抖动。"
              % (total_delta, noise))
        print("   建议：加跑第二个评分 agent，看分差是否稳定。")
        sys.exit(EXIT_REFUSED)

    verdict = "提升" if total_delta > 0 else "退步"
    print("✅ 对比有效：总分 %+d（%s → %s），判定为**%s**。"
          % (total_delta, grade_prev or "—", grade_cur or "—", verdict))

    ups = [n for n, _ in AXES if n in axes_prev and n in axes_cur
           and axes_cur[n] - axes_prev[n] > 0]
    downs = [n for n, _ in AXES if n in axes_prev and n in axes_cur
             and axes_cur[n] - axes_prev[n] < 0]
    if ups:
        print("   上升轴: " + "、".join("%s %+d" % (n, axes_cur[n] - axes_prev[n]) for n in ups))
    if downs:
        print("   下降轴: " + "、".join("%s %+d" % (n, axes_cur[n] - axes_prev[n]) for n in downs))
    if not ups and not downs:
        print("   ⚠️  四轴未测或未变化 —— 只报了总分，不得据此声称某一轴达标。")

    print("")
    print("   四轴分开报，绝不合并——用一个轴补另一个轴的分是刷分路径（公理 3）。")
    if verdict == "提升":
        print("   下一步：把这版设为新基线，继续下一次迭代。")


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

    precheck_bare_flags(argv)

    parser = _Parser(prog="eval_record.py", add_help=False)
    sub = parser.add_subparsers(dest="cmd")

    p_rec = sub.add_parser("record", add_help=False)
    for f in ("--file", "--json", "--from-file"):
        p_rec.add_argument(f, dest=f)

    p_his = sub.add_parser("history", add_help=False)
    p_his.add_argument("--file", dest="--file")

    p_cmp = sub.add_parser("compare", add_help=False)
    for f in ("--file", "--noise"):
        p_cmp.add_argument(f, dest=f)

    ns = parser.parse_args(argv)
    if ns.cmd not in ("record", "history", "compare"):
        usage_error("未知子命令: %s（合法: record / history / compare）" % ns.cmd)

    {"record": cmd_record, "history": cmd_history, "compare": cmd_compare}[ns.cmd](vars(ns))


if __name__ == "__main__":
    main()
