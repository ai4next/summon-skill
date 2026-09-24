#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 人格静态质检（P5 安装门）

对**一个** persona 的 `SKILL.md` 做静态结构检查，是 P5「安装后自检」的机器执行部分。

用法:
    python3 fidelity_check.py <persona SKILL.md 路径> [--source-dir DIR]

选项:
    --source-dir DIR    源材料根目录，用于核对 `gaps` 覆盖（默认 ./material）
                        源材料**无格式要求**；可选落盘约定见 `roster-format.md` §一
    -h, --help          打印本帮助（可放在任意位置）

退出码:
    0 = 全部通过（允许警告）
    1 = 有 FAIL，或参数 / 文件有误

材料类型:
    **实录型 `real` / 原作型 `fictional` / 合成型 `archetype`**——三条平等主路径。
    合成型的 ground truth 是 `<人格目录>/references/AXIOMS.md`（frontmatter
    `source_axioms` 是相对人格目录的路径），本脚本核对它在位且哈希一致。

本脚本**只做静态结构检查**。它查得出：
    - 双核齐备：🧠 认知层（心智模型 3-7 个 · 决策启发式 5-10 条）
                🎭 人格层（身份卡 · 表达DNA 六项 · 反模式 ≥5 条）
    - 运行层四段：角色扮演规则 / 表达DNA / 诚实边界 / 反例黑名单
    - 溯源指针（公理 2）：每条模型与启发式带 `src:`；`src: inferred` 是否点名推导链
    - 自洽性结构（公理 4）：「我自己也没想清楚的」至少 1 对显式张力
    - 闭包边界（公理 5）：诚实边界是否把「信息缺口」与「结构性沉默 / 闭包边界」分开写
    - 公理集在位（公理 2）：合成型的 `source_axioms` 可解析且哈希一致
    - frontmatter：`schema_version` · 名册必填字段（`axes` 四轴）· `description` 长度
    - 材料 `gaps` 是否逐条映射进诚实边界（源材料在本地时；不在本地则跳过）
    - 合成型是否声明「合成 · 不对应任何具体个人」（公理 5）

它**查不出**「跑起来像不像这个人」和「有没有用」。这两件事必须由**独立 agent** 跑
`references/fidelity-scorecard.md`，分四轴报 **生成力 / 自洽性 / 辨识度 / 溯源**——
四个数不合并、不自评、不互相补偿（公理 3）。**绝不能用本脚本代替评分卡，也绝不能自评。**
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _yaml_subset import (  # noqa: E402
    parse_frontmatter, as_list, as_str, as_int, as_dict, is_null, section,
    sha256_file,
)
from _material import (  # noqa: E402
    FIELD_SOURCE, SOURCE_DIR_DEFAULT, material_path as resolve_material_path,
)

PASS, WARN, FAIL = "pass", "warn", "fail"
LABEL = {PASS: "✅ PASS", WARN: "⚠️  WARN", FAIL: "❌ FAIL"}

#: 四轴（名称, 满分）——`fidelity-scorecard.md` §零
AXES = (("生成力", 30), ("自洽性", 25), ("辨识度", 20), ("溯源", 25))

#: 表达DNA 六项（canonical source：persona-forge.md §二.4）
DNA_SIX = ("句式", "词汇", "节奏", "幽默", "确定性", "引用")

#: 闭包边界 / 结构性沉默标记（公理 5）
CLOSURE_MARKS = ("结构性沉默", "闭包边界", "本质无立场", "主动不公开",
                 "主动不表态", "faithful_silence")

#: `src:` 行
SRC_RE = re.compile(r"(?:\*\*)?\s*src\s*(?:\*\*)?\s*[:：]\s*(.+)", re.I)

#: 推导链里可被「点名」的对象：模型 / 启发式 / 公理（合成型的 ground truth 是公理集）
NAMED_RE = re.compile(
    r"模型\s*[0-9一二三四五六七八九十]+"
    r"|启发式\s*[0-9一二三四五六七八九十]+"
    r"|公理\s*[A-Za-z]?\s*[0-9一二三四五六七八九十]+"
    r"|公理集"
    r"|(?<![A-Za-z0-9])[Aa]\s*\d+"
    r"|(?<![A-Za-z0-9])[mM]\s*\d+"
    r"|(?<![A-Za-z0-9])[hH]\s*\d+"
)

# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def usage_error(msg):
    """参数 / 文件错误：**stderr** + 退出码 1。"""
    sys.stderr.write("❌ " + msg + "\n")
    sys.stderr.write("用法: python3 fidelity_check.py <persona SKILL.md 路径> [--source-dir DIR]\n")
    sys.exit(1)


def _sec(body, *titles):
    """取二级标题下的正文。

    先走共享解析器的 `section()`（容忍「## 表达DNA · 🎭 人格层」这类后缀）；
    它只容忍以 `·:：—|/` 开头的后缀，所以对「## 反例黑名单（绝不要做）」再兜底一次。
    """
    got = section(body, *titles)
    if got is not None:
        return got
    for t in titles:
        m = re.search(r"^##\s+" + re.escape(t) + r"[^\n]*\n(.*?)(?=^##\s|\Z)",
                      body, re.M | re.S)
        if m:
            return m.group(1)
    return None


def _norm(s):
    return re.sub(r"\s+", "", s or "")


def _blocks(sec):
    """按 `###` 标题切块，返回 [(标题, 整块文本)]。"""
    if not sec:
        return []
    marks = list(re.finditer(r"^###\s+(.+?)\s*$", sec, re.M))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(sec)
        out.append((m.group(1).strip(), sec[m.start():end]))
    return out


def _list_items(sec):
    """把顶层列表项（含续行）分组。返回每项的整段文本。"""
    if not sec:
        return []
    lines = sec.splitlines()
    starts = [i for i, l in enumerate(lines)
              if re.match(r"^\s*(?:\d+\.|[-*+])\s+\S", l)]
    if not starts:
        return []
    base = min(len(lines[i]) - len(lines[i].lstrip()) for i in starts)
    items, cur = [], None
    for l in lines:
        ind = len(l) - len(l.lstrip())
        is_start = ind == base and re.match(r"^\s*(?:\d+\.|[-*+])\s+\S", l)
        if is_start:
            if cur is not None:
                items.append("\n".join(cur))
            cur = [l.strip()]
        elif cur is not None:
            cur.append(l.rstrip())
    if cur is not None:
        items.append("\n".join(cur))
    return items


def _table_data_rows(sec):
    """表格数据行（去掉表头与分隔行），返回单元格列表的列表。"""
    if not sec:
        return []
    lines = [l.strip() for l in sec.splitlines() if l.strip().startswith("|")]
    sep = None
    for i, l in enumerate(lines):
        if re.match(r"^\|[\s:|-]+\|$", l):
            sep = i
            break
    out = []
    for i, l in enumerate(lines):
        if i == sep:
            continue
        if sep is not None and i == sep - 1:
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if any(cells):
            out.append(cells)
    return out


def _table_src_column(sec):
    """若表格有 `src` 列，返回其列号；否则 None。"""
    lines = [l.strip() for l in (sec or "").splitlines() if l.strip().startswith("|")]
    for i, l in enumerate(lines):
        if re.match(r"^\|[\s:|-]+\|$", l):
            if i == 0:
                return None
            cells = [c.strip() for c in lines[i - 1].strip("|").split("|")]
            for j, c in enumerate(cells):
                if c.strip("`* ").lower() == "src":
                    return j
            return None
    return None


def _src_value(block):
    m = SRC_RE.search(block or "")
    if not m:
        return None
    return m.group(1).strip().strip("`*").strip()


def _is_inferred(v):
    return bool(v) and v.strip().lower().startswith("inferred")


def _without_src(text):
    return "\n".join(l for l in (text or "").splitlines() if not SRC_RE.search(l))


def _derivation_text(block):
    """模型块：去掉首行标题与 `src:` 行——否则「### 模型3」会自己点名自己。"""
    lines = (block or "").splitlines()
    out = []
    for i, ln in enumerate(lines):
        if i == 0:
            continue
        if SRC_RE.search(ln):
            continue
        out.append(ln)
    return "\n".join(out)


def _gap_covered(gap, norm_sec):
    """静态近似：`gaps` 条目是否「出现」在诚实边界里。

    先看归一化后的子串；再退回 2-gram 覆盖率 ≥0.6（容忍第一人称改写）。
    这是启发式——最终判据是评分卡「溯源 S · 缺口与边界映射」的人工核对。
    """
    g = _norm(gap)
    if not g:
        return True
    if len(g) >= 3 and g in norm_sec:
        return True
    grams = [g[i:i + 2] for i in range(len(g) - 1)]
    if not grams:
        return g in norm_sec
    hit = sum(1 for x in grams if x in norm_sec)
    return hit / len(grams) >= 0.6


def _short(s, n=24):
    s = _norm(s)
    return s if len(s) <= n else s[:n] + "…"


# --------------------------------------------------------------------------
# 档案加载：gaps + 结构性沉默
# --------------------------------------------------------------------------

def load_material(fm, source_dir):
    """→ ctx dict（gaps / material_silence / material_skipped / material_path）。"""
    ctx = {"gaps": [], "material_silence": False, "material_skipped": None, "material_path": None}
    if fm is None:
        ctx["material_skipped"] = "无 frontmatter"
        return ctx
    slug = as_str(fm.get(FIELD_SOURCE))
    if not slug:  # 块列表形态（roster.py R3 同样容忍）
        lst = as_list(fm.get(FIELD_SOURCE))
        slug = lst[0] if lst else None
    if not slug:
        ctx["material_skipped"] = "无 source_material（合成型以公理集 references/AXIOMS.md 为 ground truth）"
        return ctx
    path = resolve_material_path(source_dir, slug)
    if not path:
        # 输入是通用的：材料可以只是一段粘贴的文本，不一定在磁盘上留下文件
        ctx["material_skipped"] = ("找不到源材料文件（通用输入可不留文件）：%s"
                                   % os.path.join(source_dir, slug))
        return ctx
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        ctx["material_skipped"] = "源材料读取失败: %s" % e
        return ctx
    ctx["material_path"] = path
    afm, _abody = parse_frontmatter(text)
    if afm:
        ctx["gaps"] = as_list(afm.get("gaps"))
        for k in ("structural_silence", "silences", "silence"):
            if not is_null(afm.get(k)):
                ctx["material_silence"] = True
    if not ctx["material_silence"]:
        ctx["material_silence"] = any(k in text for k in CLOSURE_MARKS)
    return ctx


# --------------------------------------------------------------------------
# 公理集（合成型的 ground truth）
# --------------------------------------------------------------------------

def resolve_axioms_path(fm, persona_dir, source_root, slug):
    """合成型的 `source_axioms` → 实际文件路径。

    解析顺序（`persona-forge.md` §七：公理集惯例放在**人格目录自己的**
    `references/AXIOMS.md`，人格目录因此自包含、可迁移）：
      1. 绝对路径
      2. 含 `/` 或以 `.md` 结尾 → 相对**人格目录**
      3. slug 形式 → `<人格目录>/references/AXIOMS.md` → `<档案根>/<slug>/AXIOMS.md` → `<人格目录>/<slug>`
      4. 兜底：即使 frontmatter 没写，人格目录下的 `references/AXIOMS.md` 也算数
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


# --------------------------------------------------------------------------
# 检查项：每项返回 (status, detail)
# --------------------------------------------------------------------------

def check_frontmatter(fm, body, ctx):
    if fm is None:
        return FAIL, "未解析到 frontmatter——人格运行体必须有 frontmatter（不是警告，是 FAIL）"
    if not fm:
        return FAIL, "frontmatter 为空"
    return PASS, "frontmatter 已解析（%d 个字段）" % len(fm)


def check_schema_version(fm, body, ctx):
    if fm is None:
        return FAIL, "无 frontmatter，无法读取 schema_version"
    v = as_int(fm.get("schema_version"))
    if v is None:
        return FAIL, "缺少 schema_version（见 persona-template.md）"
    if v == 2:
        return PASS, "schema_version: 2"
    if v == 1:
        return WARN, "schema_version: 1（旧版；当前为 2，建议升版）"
    return FAIL, "schema_version: %s（未知；当前为 2、旧版为 1）" % v


def check_roster_fields(fm, body, ctx):
    """名册必填字段（roster-format.md §四）。

    v3：`axes`（四轴内联映射）取代 v2 的 `fidelity` / `generativity`。
    合成型的 ground truth 是公理集（`persona-forge.md` §七.3），漂移依据是
    `source_axioms_sha256`；此时 `source_material_version` 槽位不适用。
    """
    if fm is None:
        return FAIL, "无 frontmatter——名册必填字段全缺（roster-format.md §四）"
    missing = [f for f in ("name", "persona_type", "updated", "triggers", "status")
               if is_null(fm.get(f))]
    has_material = not is_null(fm.get(FIELD_SOURCE))
    has_axioms = not is_null(fm.get("source_axioms"))
    if has_material:
        # `source_material_sha256` / `_version` 是**可选**的：输入是通用的，
        # 材料可以只是一段粘贴的文本，不留文件也不算缺陷（design-philosophy.md §零）。
        pass
    elif has_axioms:
        if is_null(fm.get("source_axioms_sha256")):
            missing.append("source_axioms_sha256")
    else:
        missing.append("source_material 或 source_axioms")

    # v3：`axes` 取代 `fidelity`/`generativity`；旧字段接受但告警
    axes = as_dict(fm.get("axes"))
    has_axes = not is_null(fm.get("axes"))
    has_legacy = not is_null(fm.get("fidelity"))
    if not has_axes and not has_legacy:
        missing.append("axes")
    if missing:
        return FAIL, "名册字段缺 %d 项：%s" % (len(missing), "、".join(missing))
    if has_axes:
        lack = [n for n, _ in AXES if as_int(axes.get(n)) is None]
        if lack:
            return FAIL, "`axes` 缺轴：%s（四轴必须齐：生成力/自洽性/辨识度/溯源）" % "、".join(lack)
    if not has_axes and has_legacy:
        return WARN, "名册必填字段齐备，但 `fidelity` 字段已弃用，请改为 `axes`（四轴）"
    return PASS, "名册必填字段齐备（`axes` 四轴）"


def check_description(fm, body, ctx):
    if fm is None:
        return FAIL, "无 frontmatter，缺少 description"
    d = as_str(fm.get("description"))
    if not d or not d.strip():
        return FAIL, "缺少 description（frontmatter 必填）"
    n = len(d)
    if n > 1024:
        return FAIL, "description %d 字（>1024 硬上限；且抬高误触发率）" % n
    if n > 500:
        return WARN, "description %d 字（>500；目标约 300 字）" % n
    return PASS, "description %d 字（≤500）" % n


def check_models(fm, body, ctx):
    sec = _sec(body, "核心心智模型", "心智模型")
    if sec is None:
        return FAIL, "缺少「核心心智模型」段——认知层缺失"
    blocks = _blocks(sec)
    n = len(blocks)
    if n == 0:
        bullets = re.findall(r"^\s*(?:[-*+]|\d+\.)\s+\S", sec, re.M)
        if bullets:
            return FAIL, ("核心心智模型下只有 %d 条列表项、无 `### 模型N:` 小节——"
                          "纯 bullet 不算心智模型" % len(bullets))
        return FAIL, "核心心智模型下没有任何 `###` 模型小节"
    if n < 3:
        return FAIL, "心智模型仅 %d 个（需 3-7）" % n
    if n > 7:
        return FAIL, "心智模型 %d 个（>7，没取舍）" % n
    return PASS, "%d 个心智模型（`###` 小节）" % n


def check_limitations(fm, body, ctx):
    sec = _sec(body, "核心心智模型", "心智模型")
    if sec is None:
        return FAIL, "缺少「核心心智模型」段"
    if "待填" in sec:
        return FAIL, "模型段仍有「待填」占位符"
    blocks = _blocks(sec)
    if not blocks:
        return FAIL, "无 `###` 模型小节，无法逐条核对局限"
    missing = [h for h, t in blocks if not re.search(r"局限|失效|不适用|盲区", t)]
    if missing:
        return FAIL, "%d/%d 个模型缺「局限」行：%s" % (
            len(missing), len(blocks), "、".join(_short(x, 14) for x in missing))
    return PASS, "%d/%d 个模型都有「局限」行" % (len(blocks), len(blocks))


def check_heuristics(fm, body, ctx):
    sec = _sec(body, "决策启发式")
    if sec is None:
        return FAIL, "缺少「决策启发式」段——认知层不完整"
    n = len(_list_items(sec))
    if n == 0:
        n = len(_table_data_rows(sec))
    if n < 5:
        return FAIL, "决策启发式仅 %d 条（需 5-10）" % n
    if n > 10:
        return FAIL, "决策启发式 %d 条（>10，没取舍）" % n
    return PASS, "%d 条决策启发式" % n


def check_identity(fm, body, ctx):
    sec = _sec(body, "身份卡")
    if sec is None:
        if re.search(r"\*\*我是谁\*\*", body):
            return PASS, "检出「我是谁」身份卡（无独立小节）"
        return FAIL, "缺少「身份卡」段——人格层不完整，召不出「谁」"
    if "待填" in sec:
        return FAIL, "身份卡仍是「待填」占位符"
    if len(_norm(sec)) < 20:
        return FAIL, "身份卡内容过短（<20 字）"
    return PASS, "身份卡在位"


def check_expression_dna(fm, body, ctx):
    sec = _sec(body, "表达DNA", "表达 DNA", "表达风格")
    if sec is None:
        return FAIL, "缺少「表达DNA」段——人格层缺失（只剩一套方法论）"
    if "待填" in sec:
        return FAIL, "表达DNA 段仍有「待填」占位符"
    missing = [m for m in DNA_SIX if m not in sec]
    if missing:
        return FAIL, "表达DNA 缺 %d 项（需六项全覆盖）：%s" % (len(missing), "、".join(missing))
    return PASS, "六项全覆盖：句式/词汇/节奏/幽默/确定性/引用"


def check_anti_patterns(fm, body, ctx):
    vsec = _sec(body, "价值观与反模式", "内在张力", "矛盾与张力") or ""
    refused = 0
    m = re.search(r"\*\*我拒绝的\*\*[^\n]*\n(.*?)(?=\n\*\*|\n##|\Z)", vsec, re.S)
    if m:
        refused = len(re.findall(r"^\s*(?:[-*+]|\d+\.)\s+\S", m.group(1), re.M))
    rows = _table_data_rows(_sec(body, "反例黑名单") or "")
    alt = len(_list_items(_sec(body, "反模式") or ""))
    n = max(refused, len(rows), alt)
    if n < 5:
        return FAIL, "反模式仅 %d 条（需 ≥5）：我拒绝的 %d 条 · 反例黑名单 %d 行" % (
            n, refused, len(rows))
    return PASS, "反模式 %d 条（我拒绝的 %d · 反例黑名单 %d 行）" % (n, refused, len(rows))


def check_blacklist_section(fm, body, ctx):
    sec = _sec(body, "反例黑名单")
    if sec is None:
        return FAIL, "缺少「反例黑名单」段——四段不可删之一"
    rows = _table_data_rows(sec)
    if not rows:
        return FAIL, "「反例黑名单」段存在但无可解析条目"
    return PASS, "反例黑名单 %d 条" % len(rows)


def check_honest_boundary(fm, body, ctx):
    sec = _sec(body, "诚实边界", "Honest Boundary")
    if sec is None:
        return FAIL, "缺少「诚实边界」段——运行层不完整"
    if "待填" in sec or "[档案未列出明确缺口" in sec:
        return FAIL, "诚实边界仍是占位符（未映射源档案 gaps）"
    n = max(len(re.findall(r"^\s*(?:[-*+]|\d+\.)\s+\S", sec, re.M)),
            len(_table_data_rows(sec)))
    if n < 3:
        return FAIL, "诚实边界仅 %d 条（需 ≥3）" % n
    return PASS, "%d 条诚实边界" % n


def check_gaps_mapping(fm, body, ctx):
    if ctx.get("material_skipped"):
        return PASS, "⏭ 跳过：%s" % ctx["material_skipped"]
    gaps = ctx.get("gaps") or []
    if not gaps:
        return PASS, "源档案 gaps 为空，无需映射"
    sec = _sec(body, "诚实边界", "Honest Boundary") or ""
    norm_sec = _norm(sec)
    covered = [g for g in gaps if _gap_covered(g, norm_sec)]
    missing = [g for g in gaps if not _gap_covered(g, norm_sec)]
    ratio = 100.0 * len(covered) / len(gaps)
    if missing:
        return FAIL, "gaps 覆盖 %d/%d（%.0f%%）；未映射：%s" % (
            len(covered), len(gaps), ratio, "；".join(_short(x) for x in missing[:3]))
    return PASS, "gaps 覆盖 %d/%d（100%%）" % (len(covered), len(gaps))


def check_closure_boundary(fm, body, ctx):
    """公理 5：诚实边界必须把「信息缺口」与「结构性沉默 / 闭包边界」分开写。

    结构性沉默是**正确行为**，不是待补的缺口——把两者混在一起会逼着为沉默编造立场。
    本项为**警告级**（静态近似），最终判据在评分卡「溯源 S · 缺口与边界映射」。
    """
    sec = _sec(body, "诚实边界", "Honest Boundary") or ""
    has_gap = "信息缺口" in sec or "缺口" in sec
    boundary_marks = any(k in sec for k in CLOSURE_MARKS)
    if boundary_marks and has_gap:
        return PASS, "诚实边界已把「信息缺口」与「闭包边界 / 结构性沉默」分开写（公理 5）"
    if ctx.get("material_silence") and not boundary_marks:
        return WARN, ("源档案声明了结构性沉默，但诚实边界未单列「闭包边界 / 结构性沉默」"
                      "——沉默不是缺口（公理 5）")
    if not boundary_marks:
        return WARN, ("诚实边界未区分「信息缺口」与「结构性沉默 / 闭包边界」——"
                      "合成型须在立公理集时写明「闭包边界」（公理 5）")
    return WARN, "诚实边界有闭包边界，但未与「信息缺口」分段区分"


def check_consistency_structure(fm, body, ctx):
    """自洽性结构（公理 4）：只数「**我自己也没想清楚的**」小节下的结构化条目。

    v3 起门槛为 **≥1 对**显式张力（旧卡是 ≥2）——关键是人格**自己承认**那个冲突，
    而不是并列摆着两句相反的话。不数散落在全文的「张力 / 矛盾」关键词。
    """
    sec = _sec(body, "价值观与反模式", "内在张力", "矛盾与张力") or body
    m = re.search(r"\*\*我自己也没想清楚的\*\*[^\n]*\n(.*?)(?=\n\*\*|\n##|\Z)", sec, re.S)
    if not m:
        return FAIL, "未检出「我自己也没想清楚的」小节——张力必须写在这里（不数散落关键词）"
    n = len(re.findall(r"^\s*(?:\d+\.|[-*+])\s+\S", m.group(1), re.M))
    if n < 1:
        return FAIL, "「我自己也没想清楚的」为空（自洽性要求 ≥1 对显式张力）"
    return PASS, "%d 对未调和张力（列于「我自己也没想清楚的」）" % n


def check_provenance(fm, body, ctx):
    """公理 2 的机器可读形式：每条模型 / 启发式带 `src:`；`inferred` 须点名推导链。"""
    msec = _sec(body, "核心心智模型", "心智模型")
    blocks = _blocks(msec) if msec else []
    hsec = _sec(body, "决策启发式")
    h_items = []  # [(整段文本, src 值 或 None)]
    if hsec:
        for t in _list_items(hsec):
            h_items.append((t, _src_value(t)))
        if not h_items:  # 表格形态：优先取 `src` 列
            col = _table_src_column(hsec)
            for row in _table_data_rows(hsec):
                joined = " | ".join(row)
                if col is not None and col < len(row):
                    src = row[col].strip().strip("`*").strip()
                else:
                    src = _src_value(joined)
                h_items.append((joined, src or None))
    if not blocks and not h_items:
        return FAIL, "无模型 / 启发式条目可核对溯源"

    miss_m, bad_m = [], []
    for h, t in blocks:
        v = _src_value(t)
        if v is None:
            miss_m.append(h)
        elif _is_inferred(v) and not NAMED_RE.search(_derivation_text(t)):
            bad_m.append(h)
    miss_h, bad_h = [], []
    for i, (t, v) in enumerate(h_items, 1):
        if v is None:
            miss_h.append(str(i))
        elif _is_inferred(v) and not NAMED_RE.search(_without_src(t)):
            bad_h.append(str(i))

    problems = []
    if miss_m:
        problems.append("模型缺 src: %s" % "、".join(_short(x, 14) for x in miss_m))
    if bad_m:
        problems.append("模型 src: inferred 但推导链未点名: %s" % "、".join(_short(x, 14) for x in bad_m))
    if miss_h:
        problems.append("启发式缺 src: 第 %s 条" % "、".join(miss_h))
    if bad_h:
        problems.append("启发式 src: inferred 但推导链未点名: 第 %s 条" % "、".join(bad_h))
    if problems:
        return FAIL, "；".join(problems)
    return PASS, "模型 %d/%d + 启发式 %d/%d 带 src:；inferred 均有推导链" % (
        len(blocks), len(blocks), len(h_items), len(h_items))


def check_axioms_present(fm, body, ctx):
    """公理集在位（公理 2）：合成型的 ground truth 必须可解析且哈希一致。

    合成型不是「没有 ground truth」，是 ground truth 换成了公理集。
    没有 `AXIOMS.md` 的合成型，溯源 S 无法评分 → 直接判 D。
    """
    if fm is None:
        return FAIL, "无 frontmatter，无法核对公理集"
    ptype = as_str(fm.get("persona_type")) or ""
    if ptype != "archetype":
        return PASS, "非合成型（%s），跳过公理集在位检查" % (ptype or "?")
    raw = as_str(fm.get("source_axioms"))
    if not raw:
        return FAIL, ("合成型必须声明 `source_axioms`（相对人格目录的路径，惯例 "
                      "references/AXIOMS.md）——公理集是它的 ground truth")
    path = resolve_axioms_path(fm, ctx.get("persona_dir") or "",
                               ctx.get("source_root") or "", ctx.get("slug") or "")
    if not path or not os.path.isfile(path):
        return FAIL, "`source_axioms` 指向的公理集不存在：%s（合成型没有公理集 → 溯源 S 无法评分）" % (path or raw)
    recorded = as_str(fm.get("source_axioms_sha256"))
    if not recorded:
        return FAIL, "缺少 `source_axioms_sha256` —— 漂移检测没有依据（公理集是 ground truth）"
    try:
        actual = sha256_file(path)
    except OSError as e:
        return FAIL, "公理集读取失败: %s" % e
    if actual != recorded:
        return FAIL, ("公理集哈希不一致：frontmatter %s… vs 磁盘 %s… —— "
                      "公理集已改，需重铸或重算哈希" % (recorded[:12], actual[:12]))
    rel = os.path.relpath(path, ctx.get("persona_dir") or ".").replace(os.sep, "/")
    return PASS, "公理集在位：%s @ sha256 %s…" % (rel, actual[:12])


def check_archetype_declaration(fm, body, ctx):
    ptype = as_str((fm or {}).get("persona_type"), "") or ""
    if ptype != "archetype":
        return PASS, "非合成型（%s），跳过合成声明" % (ptype or "?")
    has_synth = "合成" in body
    has_no_person = ("不对应任何具体个人" in body or "不指向任何具体个人" in body)
    if has_synth and has_no_person:
        return PASS, "合成型已声明「合成 · 不对应任何具体个人」"
    if has_synth or has_no_person:
        return FAIL, "合成型声明不完整（须同时含「合成」与「不对应任何具体个人」）——伦理要求（公理 5）"
    return FAIL, "合成型未声明「合成 · 不对应任何具体个人」——伦理要求（公理 5）"


def check_drift_guard(fm, body, ctx):
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
        return FAIL, "防漂移机制缺失: " + "、".join(missing)
    return PASS, "角色扮演规则 + STOP + EXIT + 表达DNA"


CHECKS = [
    ("frontmatter", check_frontmatter),
    ("schema_version", check_schema_version),
    ("名册字段", check_roster_fields),
    ("description", check_description),
    ("心智模型", check_models),
    ("模型局限", check_limitations),
    ("决策启发式", check_heuristics),
    ("身份卡", check_identity),
    ("表达DNA", check_expression_dna),
    ("反模式", check_anti_patterns),
    ("反例黑名单", check_blacklist_section),
    ("诚实边界", check_honest_boundary),
    ("gaps 映射", check_gaps_mapping),
    ("闭包边界", check_closure_boundary),
    ("自洽性结构", check_consistency_structure),
    ("溯源 src:", check_provenance),
    ("公理集在位", check_axioms_present),
    ("合成型声明", check_archetype_declaration),
    ("防漂移机制", check_drift_guard),
]


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0

    source_dir = SOURCE_DIR_DEFAULT
    positional = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--source-dir":
            if i + 1 >= len(argv):
                usage_error("--source-dir 缺少目录参数")
            source_dir = argv[i + 1]
            i += 2
            continue
        if a.startswith("--source-dir="):
            source_dir = a.split("=", 1)[1]
            i += 1
            continue
        if a.startswith("-"):
            usage_error("未知选项: " + a)
        positional.append(a)
        i += 1

    if not positional:
        usage_error("缺少 persona SKILL.md 路径参数")
    if len(positional) > 1:
        usage_error("只接受一个 persona SKILL.md 路径（多余: %s）" % " ".join(positional[1:]))

    path = os.path.abspath(os.path.expanduser(positional[0]))
    if not os.path.isfile(path):
        usage_error("文件不存在: " + path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        usage_error("读取失败: %s" % e)

    fm, body = parse_frontmatter(text)
    ctx = load_material(fm, source_dir)
    ctx["persona_dir"] = os.path.dirname(path)
    ctx["slug"] = os.path.basename(os.path.dirname(path))
    ctx["source_root"] = source_dir

    results = []
    for name, fn in CHECKS:
        try:
            status, detail = fn(fm, body, ctx)
        except Exception as e:  # 单项异常不掩盖其余项
            status, detail = FAIL, "检查抛异常: %s: %s" % (type(e).__name__, e)
        results.append((name, status, detail))

    print("人格质检: %s/%s" % (os.path.basename(os.path.dirname(path)), os.path.basename(path)))
    print("=" * 62)
    passed = warned = 0
    for name, status, detail in results:
        print("  %-18s %s  %s" % (name, LABEL[status], detail))
        if status == FAIL:
            continue
        passed += 1
        if status == WARN:
            warned += 1
    print("=" * 62)

    if fm is None:
        print("  类型: ? · 源档案: ?（frontmatter 缺失）")
    else:
        ptype = as_str(fm.get("persona_type"), "?") or "?"
        src = as_str(fm.get(FIELD_SOURCE)) or as_str(fm.get("source_axioms")) or "—"
        print("  类型: %s · 源材料: %s" % (ptype, src))
    if ctx.get("material_path"):
        print("  材料: %s（gaps %d 条）" % (ctx["material_path"], len(ctx.get("gaps") or [])))
    elif ctx.get("material_skipped"):
        print("  材料: 跳过（%s）" % ctx["material_skipped"])

    print("结果: %d/%d 通过%s" % (passed, len(results), "（%d 项警告）" % warned if warned else ""))
    if passed == len(results):
        print("🎉 静态结构通过。下一步：由**独立 agent** 跑 references/fidelity-scorecard.md，"
              "分四轴报 生成力/自洽性/辨识度/溯源——不自评、不合并")
        return 0
    print("❌ 有未通过项。注意：本脚本只查静态结构，查不出「跑起来像不像」——"
          "四轴必须由独立 agent 跑 references/fidelity-scorecard.md")
    return 1


if __name__ == "__main__":
    sys.exit(main())
