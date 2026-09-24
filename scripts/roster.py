#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 人格名册（**严格只读**）

扫描已铸造的 persona，打印名册表与告警（漂移 / 冲突 / 降级 / 校准），
并核对 `roster-format.md` §四 的必填字段。

用法:
    python3 roster.py [--skills-dir ~/.claude/skills] [--source-dir material]

选项:
    --skills-dir DIR   人格所在目录（默认 ~/.claude/skills）
    --source-dir DIR   源材料根目录，用于漂移检测（默认 ./material）
                       源材料**无格式要求**；可选落盘约定见 `roster-format.md` §一
    -h, --help         打印本帮助（可放在任意位置）

名册列（canonical source：`roster-format.md` §七）:
    slug | 类型 | 来源材料 | 四轴 | 更新时间 | 触发词 | 状态
    「来源材料」列 = `slug @哈希前6位 (v版本)`；「四轴」列 = `G/C/D/S` 四个分数，
    总分与等级在紧随其后的「四轴明细」段里给（**四个数不相加**）。

四轴（canonical source：`fidelity-scorecard.md`）:
    **生成力 G（/30）· 自洽性 C（/25）· 辨识度 D（/20）· 溯源 S（/25）**——
    **四个数分开报、不相加、不互相补偿**。`FIDELITY.md` 是权威来源：轴分、总分、
    等级、`mode` 都以它为准；frontmatter 的 `axes` 缓存只补 `FIDELITY.md` 没给出的部分。

材料类型:
    **实录型 `real` / 原作型 `fictional` / 合成型 `archetype`**——三条平等主路径，
    合成型不是降级。合成型的 ground truth 是 `<人格目录>/references/AXIOMS.md`。

漂移检测（§五）:
    重算 `<source-dir>/<slug>/MATERIAL.md` 的 sha256，与 frontmatter 的
    `source_material_sha256` 比对。材料不在本地 → 记 `stale`（不是「—」）。
    合成型（`archetype`）对 `source_axioms` 指向的公理集文件做同样的哈希比对；
    找不到公理集时报 `none`（**不是降级**）。

状态判定（§四）:
    `status: active` 但质检总分缺失或 < 70 → 实际状态降级为 `draft` 并告警；
    材料哈希不一致或材料不在本地 → `stale`。**只报告，不改写文件。**

只读不写：本脚本**不创建、不修改任何文件**（包括不写 `ROSTER.md`）。
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _yaml_subset import (parse_frontmatter, as_list, as_str, as_int, as_dict,
                          is_null, sha256_file, read_text)
from _material import (FIELD_SHA256, FIELD_SOURCE, FIELD_VERSION, SOURCE_DIR_DEFAULT,
                       material_sha, material_path as resolve_material_path)

import argparse
import json
import re

USAGE = ("用法: python3 roster.py [--skills-dir ~/.claude/skills] "
         "[--source-dir material]")

#: `roster-format.md` §四 的必填字段（v3：`axes` 取代 `fidelity`/`generativity`）
REQUIRED_FIELDS = ("name", "persona_type", "source_material",
                   "axes", "updated", "triggers", "status")

#: 源材料的**可选**字段：有则漂移检测可用，**没有不算缺陷**——
#: 输入是通用的（`design-philosophy.md` §零），材料可以只是一段粘贴的文本。
OPTIONAL_MATERIAL_FIELDS = ("source_material_sha256", "source_material_version")

DEFECT_TYPES = ("style_drift", "in_scope_gap", "wrong_stance", "incoherent")
SILENCE_TYPES = ("faithful_silence",)
POLICY_TYPES = ("policy_gap",)
CALIBRATION_LIMIT = 10
FIDELITY_THRESHOLD = 70
G_THRESHOLD = 12

#: 四轴（名称, 满分）——顺序即报表顺序（`fidelity-scorecard.md` §零）
AXES = (("生成力", 30), ("自洽性", 25), ("辨识度", 20), ("溯源", 25))


# --------------------------------------------------------------------------
# 输出工具
# --------------------------------------------------------------------------

def usage_error(msg):
    sys.stderr.write("❌ " + msg + "\n")
    sys.stderr.write(USAGE + "\n")
    sys.exit(1)


class _Parser(argparse.ArgumentParser):
    """argparse 的 usage 错误统一走 stderr + exit 1（默认是 exit 2）。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("❌ " + message + "\n")
        sys.exit(1)


# --------------------------------------------------------------------------
# FIDELITY.md（四轴；兼容旧的 F/G 两轴与 v1 总分表头）
# --------------------------------------------------------------------------

#: v3 四轴表头：`**生成力 G：23/30** ｜ **自洽性 C：22/25** ｜ …`
AXIS_RES = {
    "生成力": re.compile(r"生成力\s*G?\s*[:：]\s*(\d+)\s*/\s*(\d+)"),
    "自洽性": re.compile(r"自洽性\s*C?\s*[:：]\s*(\d+)\s*/\s*(\d+)"),
    "辨识度": re.compile(r"辨识度\s*D?\s*[:：]\s*(\d+)\s*/\s*(\d+)"),
    "溯源": re.compile(r"溯源\s*S?\s*[:：]\s*(\d+)\s*/\s*(\d+)"),
}

#: 旧格式 `总分: 88/100`；v2 格式 `**保真度 F：88/100 · 等级A**`
TOTAL_RE = re.compile(r"(?:总分|保真度\s*F)\s*[:：]\s*(\d+)\s*/\s*100")
GRADE_RE = re.compile(r"等级\s*\**\s*[:：]?\s*\**\s*([ABCD])")
MODE_RE = re.compile(r"mode\s*\**\s*[:：]\s*\**\s*(full|lite)\b", re.I)


def grade_of(score):
    return "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"


def read_fidelity(path):
    """从 FIDELITY.md 抽四轴 / 总分 / 等级 / mode。

    返回 dict(exists, score, grade, mode, axes, axes_max, axes_measured,
    axes_source, g, g_measured)。表头按**最新优先**解析：
      v3 四轴 `生成力 G：NN/30 ｜ 自洽性 C：NN/25 ｜ 辨识度 D：NN/20 ｜ 溯源 S：NN/25`
      v2 两轴 `**保真度 F：NN/100 · 等级X**` + `**生成力 G：NN/20**`
      v1     `**总分：NN/100 · 等级X**`
    四轴不齐（旧人格）时 `axes_measured=False`，如实标「未测」，绝不冒充。
    """
    out = {"exists": False, "score": None, "grade": None, "mode": None,
           "axes": {}, "axes_max": {}, "axes_measured": False,
           "axes_source": None, "g": None, "g_measured": False}
    if not os.path.isfile(path):
        return out
    try:
        text = read_text(path)
    except OSError:
        return out
    out["exists"] = True

    for name, rx in AXIS_RES.items():
        m = rx.search(text)
        if m:
            out["axes"][name] = int(m.group(1))
            out["axes_max"][name] = int(m.group(2))
    out["axes_measured"] = all(n in out["axes"] for n, _ in AXES)
    if out["axes_measured"]:
        out["axes_source"] = "FIDELITY.md"
    if "生成力" in out["axes"]:
        out["g"] = out["axes"]["生成力"]
        out["g_measured"] = True

    m = TOTAL_RE.search(text)
    if m:
        out["score"] = int(m.group(1))
        gm = GRADE_RE.search(text)
        out["grade"] = gm.group(1) if gm else grade_of(out["score"])

    mm = MODE_RE.search(text)
    if mm:
        # 模板占位 `**mode**：full | lite` 不算真值，别把占位读成 full
        tail = text[mm.end():mm.end() + 12]
        if not re.match(r"\s*[|｜]\s*(?:full|lite)\b", tail, re.I):
            out["mode"] = mm.group(1).lower()
    return out


def read_axes_field(fm):
    """frontmatter 的 `axes` 内联映射（v3 四轴 QA 缓存）。

    形如 `axes: {生成力: 23, 自洽性: 22, 辨识度: 17, 溯源: 20, total: 82,
    grade: B, mode: full, date: ...}`。缺失 / 空 → None；不是映射 → present
    但 mapping=False（调用方据此告警）。
    """
    raw = fm.get("axes") if isinstance(fm, dict) else None
    if is_null(raw):
        return None
    out = {"present": True, "mapping": isinstance(raw, dict),
           "axes": {}, "total": None, "grade": None, "mode": None, "complete": False}
    if not isinstance(raw, dict):
        return out
    for name, _mx in AXES:
        v = as_int(raw.get(name))
        if v is not None:
            out["axes"][name] = v
    out["total"] = as_int(raw.get("total"))
    out["grade"] = as_str(raw.get("grade"))
    out["mode"] = as_str(raw.get("mode"))
    out["complete"] = all(n in out["axes"] for n, _ in AXES)
    return out


def merge_axes(fid, fmax):
    """把 frontmatter `axes` 缓存并进 FIDELITY.md 的解析结果。

    **`FIDELITY.md` 是权威来源**：轴分以它为准，`axes` 缓存只补它没给出的轴；
    总分 / 等级 / mode 同理，缺失时才用 `axes` 缓存（roster-format.md §三）。
    """
    if not fmax:
        return fid
    if fmax["axes"]:
        added = False
        for k, v in fmax["axes"].items():
            if k not in fid["axes"]:
                fid["axes"][k] = v
                added = True
        fid["axes_measured"] = all(n in fid["axes"] for n, _ in AXES)
        if added:
            fid["axes_source"] = ("frontmatter" if fid["axes_measured"]
                                  else "frontmatter(不齐)")
    if fid["score"] is None and fmax["total"] is not None:
        fid["score"] = fmax["total"]
    if fid["grade"] is None and fmax["grade"]:
        fid["grade"] = fmax["grade"]
    if fid["score"] is not None and not fid["grade"]:
        fid["grade"] = grade_of(fid["score"])
    if fid["mode"] is None and fmax["mode"]:
        fid["mode"] = fmax["mode"]
    if "生成力" in fid["axes"]:
        fid["g"] = fid["axes"]["生成力"]
        fid["g_measured"] = True
    return fid


# --------------------------------------------------------------------------
# FEEDBACK.jsonl（R1：跳过非 dict 的合法 JSON 行）
# --------------------------------------------------------------------------

def count_feedback(path):
    """→ (人格缺陷数, 忠实沉默数, 规则缺口数)。三类分开计，绝不合并。

    v3 起 `incoherent`（模型互相矛盾）也属人格缺陷；`context` 字段取代 `formation`，
    读旧文件时 `formation` 仅作遗留字段忽略——计数只认 `failure`。
    """
    if not os.path.isfile(path):
        return 0, 0, 0
    defects = silences = gaps = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):   # R1：`123` 是合法 JSON 但不是对象
                    continue
                t = as_str(rec.get("failure"))
                if t in DEFECT_TYPES:
                    defects += 1
                elif t in SILENCE_TYPES:
                    silences += 1
                elif t in POLICY_TYPES:
                    gaps += 1
    except OSError:
        pass
    return defects, silences, gaps


# --------------------------------------------------------------------------
# CALIBRATION.md（只读统计；写入由 calibrate.py 负责）
# --------------------------------------------------------------------------

def parse_calibration(text):
    """→ dict(active=[cells], revoked=[cells], pending=[cells])，cells 为单元格列表。"""
    out = {"active": [], "revoked": [], "pending": []}
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            title = s[3:].strip()
            if title.startswith("生效中"):
                cur = "active"
            elif title.startswith("已撤销"):
                cur = "revoked"
            elif title.startswith("待观察"):
                cur = "pending"
            else:
                cur = None
            continue
        if cur is None or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        if set(cells[0]) <= set("-: "):      # 分隔行
            continue
        if cells[0] == "#":                  # 表头
            continue
        out[cur].append(cells)
    return out


def read_calibration(path):
    """→ (exists, active_rows, revoked_rows, pending_rows)。不存在的文件返回 None 行。"""
    if not os.path.isfile(path):
        return False, [], [], []
    try:
        text = read_text(path)
    except OSError:
        return False, [], [], []
    sec = parse_calibration(text)
    active = [c for c in sec["active"] if as_int(c[0]) is not None]
    revoked = [c for c in sec["revoked"] if c and c[0] != "—"]
    pending = [c for c in sec["pending"] if as_int(c[0]) is not None]
    return True, active, revoked, pending


def _split_list(v):
    """frontmatter 列表：行内列表用 as_list；裸逗号串按逗号切（容错）。"""
    if isinstance(v, str):
        return [x.strip().strip("[]") for x in v.split(",") if x.strip()]
    return [as_str(x) for x in as_list(v) if as_str(x)]


# --------------------------------------------------------------------------
# 漂移（R7）
# --------------------------------------------------------------------------

def resolve_axioms_path(fm, persona_dir, source_root, slug):
    """合成型（`archetype`）的 `source_axioms` → 实际文件路径。

    解析顺序（`persona-forge.md` §七：公理集惯例放在**人格目录自己的** `references/AXIOMS.md`，
    这样人格目录是自包含、可迁移的）：
      1. 绝对路径
      2. 含 `/` 或以 `.md` 结尾 → 相对**人格目录**
      3. slug 形式 → `<人格目录>/references/AXIOMS.md` → `<源材料根>/<slug>/AXIOMS.md` → `<人格目录>/<slug>`
      4. 兜底：即使 frontmatter 没写，人格目录下的 `references/AXIOMS.md` 也算数

    返回 None 表示「这个合成型确实没有公理集」（→ 报 none，不是 stale）。
    """
    raw = as_str(fm.get("source_axioms"))
    conv = os.path.join(persona_dir, "references", "AXIOMS.md")
    candidates = []
    if raw:
        if os.path.isabs(raw):
            candidates.append(raw)
        elif "/" in raw or raw.endswith(".md"):
            candidates.append(os.path.join(persona_dir, raw))
        else:
            candidates += [conv,
                           os.path.join(source_root, raw, "AXIOMS.md"),
                           os.path.join(persona_dir, raw)]
    if os.path.isfile(conv):
        candidates.append(conv)
    if not candidates:
        return None
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


def compute_drift(ptype, slug, recorded, fm, persona_dir, source_root):
    """→ (state, detail)。state ∈ ok / stale / unknown / none。

    **输入是通用的**（`design-philosophy.md` §零）：材料可以只是一段粘贴的文本，
    未必在磁盘上留下文件。所以漂移检测是**机会性**的，不是要求：

      · 记录了哈希 + 文件在 + 一致    → `ok`
      · 记录了哈希 + 文件在 + 不一致  → `stale`（**真漂移**，该重铸）
      · 记录了哈希 + 文件找不到      → `unknown`（当时有文件，现在核对不了）
      · 没记录哈希（通用输入）        → `none`（无法检测，**不是缺陷**）

    `archetype` 带 `source_axioms` → 对公理集文件做同样的哈希比对。
    """
    if ptype == "real":
        actual = material_sha(source_root, slug)
        if not recorded:
            return "none", "未记录材料哈希（通用输入可不留文件）——无法检测漂移"
        if actual is None:
            return "unknown", "源材料不在本地，无法核对"
        return ("ok", "同步") if actual == recorded else ("stale", "源材料已更新")

    if ptype == "archetype":
        ax = resolve_axioms_path(fm, persona_dir, source_root, slug)
        if ax:
            rec = as_str(fm.get("source_axioms_sha256")) or recorded
            actual = sha256_file(ax) if os.path.isfile(ax) else None
            if actual is None:
                return "unknown", "公理集不在本地"
            if not rec:
                return "unknown", "无哈希"
            return ("ok", "同步") if actual == rec else ("stale", "公理集已更新")
        if slug and slug != "—":
            return compute_drift("real", slug, recorded, fm, persona_dir, source_root)
        return "none", "合成型无公理集"

    if ptype == "fictional":
        if slug and slug != "—":
            path = resolve_material_path(source_root, slug)
            if path:
                return compute_drift("real", slug, recorded, fm, persona_dir, source_root)
        return "none", "原作型：未提供本地原作资料——无法检测漂移"

    return "none", "—"


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def collect(skills_dir, source_root):
    """扫描人格目录。返回 (rows, rejected, trigger_map, feedback_map)。"""
    rows, rejected = [], []
    trigger_map, feedback_map = {}, {}

    for entry in sorted(os.listdir(skills_dir)):
        d = os.path.join(skills_dir, entry)
        if not os.path.isdir(d) or not entry.endswith("-persona"):
            continue

        rec = {"slug": entry, "dir": d, "excluded": False, "status_error": None,
               "errors": [], "warnings": [], "fields_missing": [],
               "ptype": "?", "src_slug": "—", "src_display": "—",
               "fid": read_fidelity(os.path.join(d, "FIDELITY.md")),
               "updated": "—", "triggers": [], "declared": "—", "effective": "—",
               "drift": "none", "drift_detail": "—",
               "fb": (0, 0, 0), "calib": (False, [], [], [])}

        skill_path = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill_path):
            # R2：错误进「状态」列，且不进 src_count
            rec["status_error"] = "❌ 缺 SKILL.md"
            rec["effective"] = rec["status_error"]
            rec["errors"].append("缺 SKILL.md —— 这不是人格目录")
            rows.append(rec)
            continue

        try:
            fm, _body = parse_frontmatter(read_text(skill_path))
        except OSError:
            fm = None
        fm = as_dict(fm)

        # v3：frontmatter `axes` 缓存并入 FIDELITY.md 的解析结果
        fmax = read_axes_field(fm)
        rec["fid"] = merge_axes(rec["fid"], fmax)

        # R5：目录名与 frontmatter 的 name 必须一致，否则拒绝收录
        name = as_str(fm.get("name"))
        if name != entry:
            rejected.append((entry, "frontmatter name = %s，与目录名不一致"
                             % ("（缺）" if name is None else "`%s`" % name)))
            continue

        # 必填字段（v3：`axes` 取代 `fidelity`；合成型以 `source_axioms` 替代 `source_material`）
        required = list(REQUIRED_FIELDS)
        ptype = as_str(fm.get("persona_type"))
        if ptype == "archetype" and not is_null(fm.get("source_axioms")):
            required = [f for f in required if f != FIELD_SOURCE]
            if is_null(fm.get("source_axioms_sha256")):
                required.append("source_axioms_sha256")
        has_axes = not is_null(fm.get("axes"))
        has_legacy = not is_null(fm.get("fidelity"))   # v2 遗留，接受但告警
        missing = []
        for f in required:
            if f == "axes":
                if not has_axes and not has_legacy:
                    missing.append("axes")
                continue
            if is_null(fm.get(f)):
                missing.append(f)
        rec["fields_missing"] = missing
        if missing:
            rec["warnings"].append("缺必填字段: " + "、".join(missing))
        if has_legacy and not has_axes:
            rec["warnings"].append("`fidelity` 字段已弃用，请改为 `axes`（四轴）")
        if (ptype != "archetype" and not is_null(fm.get(FIELD_SOURCE))
                and is_null(fm.get(FIELD_SHA256))):
            rec["warnings"].append(
                "未记录 `source_material_sha256`——漂移检测对该人格不可用"
                "（通用输入可不留文件，**不算缺陷**）")
        if has_axes and fmax and not fmax["mapping"]:
            rec["warnings"].append("`axes` 不是内联映射（应为 "
                                   "{生成力: N, 自洽性: N, 辨识度: N, 溯源: N, total: N}）")
        elif has_axes and fmax and not fmax["complete"]:
            lack = [n for n, _ in AXES if n not in fmax["axes"]]
            rec["warnings"].append("`axes` 缺轴：%s（四轴必须齐）" % "、".join(lack))

        # R3：source_material 可能是块列表 → 非字符串按「未知」处理
        slug = as_str(fm.get(FIELD_SOURCE))
        rec["ptype"] = ptype or "?"
        recorded = as_str(fm.get(FIELD_SHA256)) or ""
        version = as_int(fm.get(FIELD_VERSION))
        rec["updated"] = as_str(fm.get("updated")) or "—"

        if slug:
            hash6 = recorded[:6] if recorded else "—"
            rec["src_slug"] = slug
            rec["src_display"] = "%s @%s%s" % (slug, hash6,
                                               " (v%d)" % version if version is not None else "")
        elif rec["ptype"] == "archetype":
            ax = as_str(fm.get("source_axioms")) or "—"
            rec["src_display"] = "公理集 %s" % ax
            rec["src_slug"] = "—"
        elif not is_null(fm.get(FIELD_SOURCE)):
            # R3：YAML 块列表（list）不是字符串 —— 按「未知」处理并说明，绝不 os.path.join
            rec["warnings"].append("`source_material` 不是字符串（可能是块列表），按未知源材料处理")

        # R7：漂移
        rec["drift"], rec["drift_detail"] = compute_drift(
            rec["ptype"], slug or "—", recorded, fm, d, source_root)

        # 触发词（R8：保留原始字符串，供子串比对）
        rec["triggers"] = [t for t in _split_list(fm.get("triggers")) if t]
        for t in rec["triggers"]:
            trigger_map.setdefault(t, []).append(entry)

        # 反馈三类分开计
        rec["fb"] = count_feedback(os.path.join(d, "FEEDBACK.jsonl"))
        if rec["fb"][0]:
            feedback_map[entry] = rec["fb"]

        # 校准层（只读统计）
        rec["calib"] = read_calibration(os.path.join(d, "CALIBRATION.md"))

        # R6：状态降级（只报告，不改文件）
        declared = as_str(fm.get("status")) or "—"
        rec["declared"] = declared
        eff = declared
        if declared != "retired":
            if rec["drift"] == "stale":
                eff = "stale"
                rec["warnings"].append(
                    "状态降级: `%s` → `stale`（%s）" % (declared, rec["drift_detail"]))
            elif declared == "active" and rec["fid"]["score"] is None:
                eff = "draft"
                rec["warnings"].append(
                    "状态降级: `active` → `draft`（质检总分缺失：FIDELITY.md 与 "
                    "frontmatter `axes` 都没给出 total）")
            elif declared == "active" and rec["fid"]["score"] < FIDELITY_THRESHOLD:
                eff = "draft"
                rec["warnings"].append(
                    "状态降级: `active` → `draft`（质检总分 %d < B/%d）"
                    % (rec["fid"]["score"], FIDELITY_THRESHOLD))
        rec["effective"] = eff
        rows.append(rec)

    return rows, rejected, trigger_map, feedback_map


def find_conflicts(rows, trigger_map):
    """R8：触发词冲突 —— 完全相同 + 一方是另一方的子串。"""
    problems = []
    for t, users in sorted(trigger_map.items()):
        if len(users) > 1:
            problems.append("触发词冲突「%s」同时属于 %s —— 完全相同，必须消解"
                            % (t, "、".join(users)))

    pairs = sorted({(t, u) for t, us in trigger_map.items() for u in us})
    seen = set()
    for short, su in pairs:
        for long, lu in pairs:
            if short == long or su == lu or short not in long:
                continue
            key = (short, long, su, lu)
            if key in seen:
                continue
            seen.add(key)
            problems.append(
                "触发词子串重叠：「%s」是「%s」的子串（%s ⊂ %s）—— 保留长词「%s」，删除短词「%s」（短词会误触发）"
                % (short, long, su, lu, long, short))
    return problems


def _axis_line(f):
    """四轴明细的一行文本（四个数分开，绝不相加）。"""
    if f["axes_measured"]:
        return " · ".join("%s %d/%d" % (name, f["axes"][name], mx)
                          for name, mx in AXES)
    if f["g_measured"]:
        return "旧格式 生成力 G %d/%s（四轴未测）" % (
            f["g"], f["axes_max"].get("生成力", "?"))
    return "四轴 未测"


def _axis_flags(f):
    """按 `fidelity-scorecard.md` §五 的红线给单个人格标旗。"""
    flags = []
    if f["score"] is not None and f["score"] < FIDELITY_THRESHOLD:
        flags.append("⚠️ 总分 < B")
    if f["axes_measured"]:
        if f["axes"].get("溯源") == 0:
            flags.append("❌ 溯源 S=0 → 判 D")
        if f["axes"].get("自洽性", 99) < 15:
            flags.append("⚠️ 自洽性 C<15")
        if f["axes"].get("辨识度", 99) < 12:
            flags.append("⚠️ 辨识度 D<12")
        if f["axes"].get("生成力", 99) < G_THRESHOLD:
            flags.append("⚠️ 生成力 G<%d（复读机）" % G_THRESHOLD)
    else:
        flags.append("⚠️ 四轴未测，不得声称达标")
    return flags


def _axis_cell(f):
    """名册「四轴」列：`G23 C22 D17 S20` 四个分数（**不加总**；总分在四轴明细段）。"""
    if not f["axes_measured"]:
        return "未测"
    a = f["axes"]
    return "G%d C%d D%d S%d" % (a["生成力"], a["自洽性"], a["辨识度"], a["溯源"])


def render(rows, rejected, trigger_map, feedback_map, skills_dir):
    print("人格名册 · 共 %d 个%s · 扫描自 %s"
          % (len(rows), "（另有 %d 个未收录）" % len(rejected) if rejected else "",
             skills_dir))
    print("")
    print("| slug | 类型 | 来源材料 | 四轴 | 更新时间 | 触发词 | 状态 |")
    print("|------|------|---------|--------|---------|--------|------|")
    for r in rows:
        cell = "—" if r["status_error"] else _axis_cell(r["fid"])
        print("| %s | %s | %s | %s | %s | %s | %s |" % (
            r["slug"], r["ptype"], r["src_display"], cell, r["updated"],
            "、".join(r["triggers"]) or "—", r["effective"]))

    # ---- 四轴明细（`fidelity-scorecard.md`：四个数分开报，不相加）----
    print("")
    print("四轴明细（生成力 G/30 · 自洽性 C/25 · 辨识度 D/20 · 溯源 S/25）")
    print("  **四个数分开报、不相加、不互相补偿**（design-philosophy.md 公理 3）")
    for r in rows:
        if r["status_error"]:
            continue
        f = r["fid"]
        total = ("总分 %d/100 (%s)" % (f["score"], f["grade"])
                 if f["score"] is not None else "总分 未测")
        flags = _axis_flags(f)
        print("  %-26s %s · %s · mode %s%s" % (
            r["slug"], total, _axis_line(f), f["mode"] or "未标",
            (" · " + " · ".join(flags)) if flags else ""))

    # ---- 漂移 / 冲突 / 降级 / 字段 ----
    problems = []
    for r in rows:
        if r["drift"] == "stale":
            problems.append("漂移：%s 的来源材料 %s %s —— 人格可能已过时，建议重铸"
                            % (r["slug"], r["src_slug"], r["drift_detail"]))
        elif r["drift"] == "unknown" and r["src_slug"] != "—":
            problems.append("漂移：%s %s" % (r["slug"], r["drift_detail"]))
    problems.extend(find_conflicts(rows, trigger_map))

    src_count = {}
    for r in rows:
        if r["status_error"] or r["src_slug"] == "—":   # R2：错误行不进 src_count
            continue
        src_count.setdefault(r["src_slug"], []).append(r["slug"])
    for slug, users in sorted(src_count.items()):
        if len(users) > 1:
            problems.append("同一源材料 `%s` 铸了 %d 次: %s —— 确认是否有意为之"
                            % (slug, len(users), "、".join(users)))

    for r in rows:
        for w in r["warnings"]:
            problems.append("%s: %s" % (r["slug"], w))
        if r["status_error"]:
            problems.append("%s: %s" % (r["slug"], r["status_error"]))

    unmeasured = [r["slug"] for r in rows if not r["status_error"]
                  and r["fid"]["score"] is None]
    if unmeasured:
        problems.append("未跑质检评分卡（总分未测）: " + "、".join(unmeasured))

    print("")
    print("告警与漂移（%d 处）" % len(problems))
    if problems:
        for p in problems:
            print("  ⚠️  " + p)
    else:
        print("  ✅ 未检出漂移 / 冲突 / 降级")

    # ---- 拒绝收录（R5）----
    if rejected:
        print("")
        print("❌ 拒绝收录（roster-format.md §二：目录名与 frontmatter 的 name 必须一致）")
        for entry, why in rejected:
            print("  ❌ %s —— %s" % (entry, why))

    # ---- 校准层 ----
    print("")
    print("运行侧校准（CALIBRATION.md，见 references/calibration.md §五）")
    over = []
    any_calib = False
    for r in rows:
        if r["status_error"]:
            continue
        exists, active, revoked, pending = r["calib"]
        if not exists:
            continue
        any_calib = True
        line = "  %-26s ✅ 存在 · 生效中 %d 条 · 已撤销 %d 条 · 待观察 %d 条" % (
            r["slug"], len(active), len(revoked), len(pending))
        if len(active) > CALIBRATION_LIMIT:
            line += " · ⚠️ 超过 %d 条上限" % CALIBRATION_LIMIT
            over.append(r["slug"])
        print(line)
    if not any_calib:
        print("  — 无 CALIBRATION.md（运行侧问题出现时用 calibrate.py add 建立）")
    if over:
        print("  ⚠️  %s 的「生效中」超过 %d 条 —— 停止追加：根因在源材料或人格本身，该重铸了"
              % ("、".join(over), CALIBRATION_LIMIT))

    # ---- 反馈 ----
    if feedback_map:
        print("")
        print("使用反馈（人格缺陷才计入汇总）")
        for name, (dfc, sil, gap) in sorted(feedback_map.items(), key=lambda kv: -kv[1][0]):
            print("  %-26s 人格缺陷 %d 条 · 忠实沉默 %d 条 · 规则缺口 %d 条"
                  % (name, dfc, sil, gap))
        print("  下一步：由**用户**决定是否据此修订源材料；修订后材料哈希改变。")
        print("  注意：反馈文件不改材料哈希，**不会**自动触发上面的漂移检测。")

    print("")
    measured = [r for r in rows if not r["status_error"] and r["fid"]["score"] is not None]
    ok_b = [r for r in measured if r["fid"]["score"] >= FIDELITY_THRESHOLD]
    g_ok = [r for r in rows if not r["status_error"] and r["fid"]["axes_measured"]
            and r["fid"]["axes"].get("生成力", -1) >= G_THRESHOLD]
    print("  共 %d 个人格 · 总分 ≥B 的 %d 个 · 生成力 G ≥%d 的 %d 个（四轴分开报，不相加）"
          % (len(rows), len(ok_b), G_THRESHOLD, len(g_ok)))


def main():
    argv = sys.argv[1:]
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        sys.exit(0)

    parser = _Parser(prog="roster.py", add_help=False)
    parser.add_argument("--skills-dir", default="~/.claude/skills")
    parser.add_argument("--source-dir", dest="source_dir", default=SOURCE_DIR_DEFAULT)
    ns = parser.parse_args(argv)

    skills_dir = os.path.expanduser(ns.skills_dir)
    source_root = os.path.abspath(os.path.expanduser(ns.source_dir))

    if not os.path.isdir(skills_dir):
        sys.stderr.write("❌ 人格目录不存在: %s\n" % skills_dir)
        sys.stderr.write("   用 --skills-dir 指定，或先铸一个人格试试。\n")
        sys.exit(1)

    rows, rejected, trigger_map, feedback_map = collect(skills_dir, source_root)

    if not rows and not rejected:
        print("名册为空：%s 下没有 *-persona 目录。" % skills_dir)
        print("先铸一个人格：python3 scripts/forge_scaffold.py <MATERIAL.md> --out <人格目录>")
        sys.exit(0)

    render(rows, rejected, trigger_map, feedback_map, skills_dir)


if __name__ == "__main__":
    main()
