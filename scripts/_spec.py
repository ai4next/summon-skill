#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 产物契约常量与共享工具（**唯一实现**）

**为什么这个文件存在**：四轴分值（`生成力 30 / 自洽性 25 / 辨识度 20 / 溯源 25`）
曾在 4 个脚本里各写一遍，红线阈值一处是字典、一处是内联字面量，
`grade_of` / `resolve_axioms_path` / `check_persona_dir` 各有两份逐字相同的实现。

`_yaml_subset.py` 开篇那句「**复制是漂移的根因**」对常量同样成立：
改一次分值要改八处（4 个脚本 + 4 处文档），而没有任何检查会发现漏改。

所以：**数值常量、枚举、等级线、路径解析、写盘工具，只在这里定义一次。**
所有脚本必须 `from _spec import ...`，不得再各自实现。
`scripts/selfcheck.py` 会机械检查这条纪律。

人读的说明（分值与门槛的 canonical source）：
    · 四轴定义与判据   → `references/fidelity-scorecard.md`
    · 名册字段与状态推导 → `references/roster-format.md` §四
"""

import os
import sys

from _yaml_subset import as_str
from _material import MATERIAL_MARKERS

# ==========================================================================
# 四轴（`fidelity-scorecard.md` §零）
# ==========================================================================

#: （名称, 满分）——顺序即报表顺序
AXES = (("生成力", 30), ("自洽性", 25), ("辨识度", 20), ("溯源", 25))

#: {轴名: 满分}
AXIS_MAX = dict(AXES)

#: 四轴满分之和（= 总分满分）
AXES_TOTAL = sum(mx for _n, mx in AXES)

#: 等级线（从高到低）；低于最低一条 → D
GRADE_CUTOFFS = (("A", 85), ("B", 70), ("C", 55))


def grade_of(score):
    """总分 → 等级 A/B/C/D（`fidelity-scorecard.md` §五）。"""
    for name, floor in GRADE_CUTOFFS:
        if score >= floor:
            return name
    return "D"


# ==========================================================================
# 门槛与红线（`fidelity-scorecard.md` §五）
# ==========================================================================

#: 可用门槛：总分 ≥ 此值才可留在 `active`
TOTAL_THRESHOLD = 70

#: 生成力红线：低于此值标「复读机」（**不降级**，但不得声称能提供新视角）
G_THRESHOLD = 12

#: 分轴红线：**低于**该值即触红线（溯源 0 = 存在编造/假推断 → 直接判 D）
#: 注意 `溯源` 的红线是 0（严格小于才算），与其它三条同形：`score < redline`
AXIS_REDLINE = {"生成力": 12, "自洽性": 15, "辨识度": 12, "溯源": 0}

#: 轴名 → 单字母（报表与旗标里用）
AXIS_LETTER = {"生成力": "G", "自洽性": "C", "辨识度": "D", "溯源": "S"}


def axis_redlines(axes):
    """→ [旗标文本]，只含**已触发**的红线（`fidelity-scorecard.md` §五）。

    修正 frontmatter 是人的动作：本函数只产旗标，不改任何文件
    （`roster-format.md` §四）。
    """
    flags = []
    for name, red in AXIS_REDLINE.items():
        score = axes.get(name)
        if score is None:
            continue
        if score < red:
            if name == "溯源":
                flags.append("❌ 溯源 S=0 → 判 D")
            elif name == "生成力":
                flags.append("⚠️ 生成力 G<%d（复读机）" % red)
            else:
                flags.append("⚠️ %s %s<%d" % (name, AXIS_LETTER[name], red))
    return flags


# ==========================================================================
# 计数门槛（各 canonical 小节）
# ==========================================================================

MODEL_COUNT = (3, 7)          # 心智模型（`persona-forge.md` §2.1）
HEURISTIC_COUNT = (5, 10)     # 决策启发式（§2.2）
ANTI_PATTERN_MIN = 5          # 反模式（§2.5）
HONEST_BOUNDARY_MIN = 3       # 诚实边界（§2.6）
AXIOM_COUNT = (3, 7)          # 公理集（§3.1）

#: 内在张力门槛。**两级，不是矛盾**（`persona-forge.md` §3.3）：
#:   · 硬门禁 = 1 对 —— 少于 1 对说明公理集里缺一条真正有代价的立场，静态检查判 FAIL
#:   · 质量目标 = 2 对 —— 评分卡的满分条件，也是 §八 清单的验收线
#: 只写 1 对可以出厂，但拿不到张力在位的满分。
TENSION_MIN_GATE = 1
TENSION_MIN_TARGET = 2

#: 运行侧校准「生效中」上限：超过说明根因在材料或人格本身（`roster-format.md` §5.4）
CALIBRATION_LIMIT = 10

#: 单次 LLM 评分的噪声带（分）。分数差落在此带内不构成趋势结论。
NOISE_BAND = 10

#: `description` 长度：超过 WARN 提醒，超过 MAX 直接报错（`persona-template.md`）
DESC_WARN = 500
DESC_MAX = 1024

# ==========================================================================
# 枚举
# ==========================================================================

PERSONA_TYPES = ("real", "fictional", "archetype")
STATUSES = ("active", "stale", "draft", "retired")
CONTEXTS = ("session", "review", "eval")

#: 失败类型三分（`roster-format.md` §5.2）——只有第一类计入缺陷汇总
DEFECT_TYPES = ("style_drift", "in_scope_gap", "wrong_stance", "incoherent")
SILENCE_TYPES = ("faithful_silence",)   # 忠实沉默：不计入缺陷
POLICY_TYPES = ("policy_gap",)          # 规则缺口：不计入缺陷

# ==========================================================================
# 路径与命名
# ==========================================================================

#: 人格目录固定后缀——`roster.py` 只扫这个后缀（命名空间隔离）
PERSONA_SUFFIX = "-persona"

#: 人格目录的入口文件——没有它就不是一个可运行的人格目录
PERSONA_ENTRY = "SKILL.md"

#: 人格目录内公理集的惯例相对路径（`persona-forge.md` §3.1）
AXIOMS_REL_DEFAULT = "references/AXIOMS.md"


def resolve_axioms_path(fm, persona_dir, source_root, slug):
    """合成型（`archetype`）的 `source_axioms` → 实际文件路径。

    解析顺序（`persona-forge.md` §3.1：公理集惯例放在**人格目录自己的**
    `references/AXIOMS.md`，人格目录因此自包含、可迁移）：
      1. 绝对路径
      2. 含 `/` 或以 `.md` 结尾 → 相对**人格目录**
      3. slug 形式 → `<人格目录>/references/AXIOMS.md` → `<源材料根>/<slug>/AXIOMS.md` → `<人格目录>/<slug>`
      4. 兜底：即使 frontmatter 没写，人格目录下的 `references/AXIOMS.md` 也算数

    返回 `None` 表示「这个合成型确实没有公理集」（→ 漂移报 `none`，不是 `stale`）。
    """
    raw = as_str(fm.get("source_axioms"))
    conv = os.path.join(persona_dir, AXIOMS_REL_DEFAULT)
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


# ==========================================================================
# 写边界（`roster-format.md` §一：材料归用户，人格归 summon）
# ==========================================================================

def check_persona_dir(pdir, markers=MATERIAL_MARKERS, prefix="❌ 拒绝写入"):
    """白名单式归属校验。通过则返回目录名，否则 `sys.exit(1)`。

    **这是本 skill 唯一的硬写边界**：三个会写盘的脚本（`feedback_log` /
    `calibrate` / `eval_record`）都必须先过这一关，否则
    `--file material/munger/EVALS.jsonl` 这类调用会写进用户的材料目录。

    规则（四条，全部来自 `roster-format.md` §一）：
      1. 目录必须存在
      2. 目录名必须以 `-persona` 结尾（命名空间隔离）
      3. 目录里不得含 `MATERIAL.md` / `manifest.json` / `QUALITY.md`
         （那是**材料目录**，不是人格目录）
      4. 目录里必须有 `SKILL.md`（人格本体）
    """
    if not os.path.isdir(pdir):
        _refuse(prefix, ["人格目录不存在: " + pdir])
    slug = os.path.basename(os.path.abspath(pdir).rstrip(os.sep))
    if not slug.endswith(PERSONA_SUFFIX):
        _refuse(prefix, [
            "目录名 `%s` 不以 `%s` 结尾 —— 这不是本 skill 的人格目录。" % (slug, PERSONA_SUFFIX),
            "归属约束（白名单）：只写 `~/.claude/skills/<slug>%s/`。" % PERSONA_SUFFIX,
        ])
    for marker in markers:
        if os.path.isfile(os.path.join(pdir, marker)):
            _refuse(prefix, [
                "该目录含 %s，是**源材料目录**，不是人格目录。" % marker,
                "归属约束：材料归用户，人格归 summon；summon 只读材料，绝不写材料目录。",
            ])
    if not os.path.isfile(os.path.join(pdir, PERSONA_ENTRY)):
        _refuse(prefix, [
            "该目录没有 `%s` —— 人格目录必须含人格本体。" % PERSONA_ENTRY,
            "请把 --persona-dir 指向 ~/.claude/skills/<slug>%s/。" % PERSONA_SUFFIX,
        ])
    return slug


def _refuse(prefix, lines):
    sys.stderr.write("%s: %s\n" % (prefix, lines[0]))
    for ln in lines[1:]:
        sys.stderr.write("   " + ln + "\n")
    sys.exit(1)


def refuse_material_dir(target_path, markers=MATERIAL_MARKERS):
    """拒绝把运行记录写进**材料目录**（`roster-format.md` §一）。

    与 `check_persona_dir` 的分工：
      · `check_persona_dir` 要求目录本身是 `<slug>-persona/`（写**人格本体**的脚本用）
      · 本函数只看「目标所在目录里有没有材料标记」（写**显式路径**的脚本用，
        如 `eval_record.py --file`——调用方自己指定路径，不必是人格目录，
        但**绝不能是用户的材料目录**）

    这是「材料归用户，人格归 summon」这条单向写边界在 `eval_record` 上的落点：
    此前只有 `feedback_log` / `calibrate` 有守卫，`eval_record --file
    material/munger/EVALS.jsonl` 会直接写进用户的材料目录。
    """
    d = os.path.dirname(os.path.abspath(target_path)) or "."
    for marker in markers:
        if os.path.isfile(os.path.join(d, marker)):
            _refuse("❌ 拒绝写入", [
                "目标目录含 %s，是**源材料目录**，不是本 skill 的地盘。" % marker,
                "归属约束：材料归用户，人格归 summon；summon 只读材料，绝不写材料目录。",
            ])


def require_text(args, flag, why, usage_error):
    """取一个非空字符串选项；缺失 / 空串 / 非字符串一律 usage_error。"""
    v = args.get(flag)
    if v is None:
        usage_error("缺少 %s（%s）" % (flag, why))
    if not isinstance(v, str) or not v.strip():
        usage_error("%s 必须是**非空字符串**（%s）" % (flag, why))
    return v.strip()


# ==========================================================================
# 原子写盘
# ==========================================================================

def write_text_atomic(path, text):
    """原子写 UTF-8 文本：写临时文件 → `os.replace`。

    **为什么必须原子**：`calibrate.py` 整文件重写 `CALIBRATION.md`，
    `forge_scaffold.py` 重写人格 `SKILL.md`。裸 `open(path,"w")` 在
    写到一半崩溃 / 磁盘满时会**截断原文件**——校准历史清零、人格损坏。
    临时文件 + `os.replace`（同目录，POSIX 原子）让「要么全旧、要么全新」。

    失败抛 `OSError`，由调用方给一句人话。
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    tmp = os.path.join(d, ".%s.tmp.%d" % (os.path.basename(path), os.getpid()))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


# ==========================================================================
# argparse 统一行为：usage 错误走 stderr + exit 1（默认是 exit 2）
# ==========================================================================

def make_usage_error(usage, extra=None):
    """→ 该脚本专用的 `usage_error(msg)`。

    `extra` 是用法行之后、错误信息之前的固定提示行（`feedback_log` 用它列失败类型）。
    """
    def usage_error(msg):
        sys.stderr.write("❌ " + msg + "\n")
        sys.stderr.write(usage + "\n")
        if extra:
            sys.stderr.write(extra)
        sys.exit(1)
    return usage_error


def usage_parser(prog, usage=None, add_help=True, error_prefix="❌ 参数错误: ",
                 description=None):
    """argparse 子类：usage 错误统一走 stderr + `exit 1`（argparse 默认是 2）。

    四个脚本曾各写一份几乎逐字相同的 `class _Parser`。两个变体在这里合一：
      · `usage` 给了 → 打印这行用法；没给 → 用 argparse 的 `print_usage`
      · `error_prefix` 决定前缀（名册用「❌ 」，其余用「❌ 参数错误: 」）
      · `description` 透传给 argparse（`forge_scaffold` 用 `__doc__` 作帮助正文）
    """
    import argparse

    class _UsageParser(argparse.ArgumentParser):
        def error(self, message):
            if usage:
                sys.stderr.write(usage + "\n")
            else:
                self.print_usage(sys.stderr)
            sys.stderr.write(error_prefix + message + "\n")
            sys.exit(1)

    return _UsageParser(prog=prog, add_help=add_help, description=description,
                        formatter_class=argparse.RawDescriptionHelpFormatter)
