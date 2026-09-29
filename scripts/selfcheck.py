#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 仓库机械自检（查**本 skill 自身**，不是人格）

每一次人工审计发现的缺陷，都应该是**机械可检**的——这个脚本把它们固化下来，供 CI 跑。
它不评价文档写得好不好，只核对「说到的文件在不在」「脚本和文档的契约对不对得上」。

用法:
    python3 scripts/selfcheck.py [--root DIR] [--json] [--quiet]

选项:
    --root DIR   仓库根目录（默认：本脚本所在目录的上一级）
    --json       输出机器可读 JSON（供 CI 消费）
    --quiet      只打印失败 / 警告项与汇总
    -h, --help   打印本帮助（可放在任意位置）

退出码:
    0 = 无 FAIL（警告不阻塞）
    1 = 有 FAIL，或参数有误

十五项检查:
     1. 引用文件存在性      活跃 markdown 里内联代码的 references/*.md、scripts/*.py、examples/* 是否存在
     2. 废弃术语            活跃文档（SKILL.md / README.md / references/*.md）不得把 四阵型 / 圆桌 / 遣将 / panel / 主持人 / 原型型 当作**功能**描述
     3. 路由表完整性        SKILL.md §四 路由表点名的 canonical source 是否存在
     4. canonical source 纪律  design-philosophy.md §四 点名的文件是否存在，且本文件被 SKILL.md 引用
     5. frontmatter 解析器唯一性  任何 scripts/*.py 不得自定义 parse_frontmatter / parse_scalar
     6. 脚本 --help 支持    每个 scripts/*.py 跑 --help 须 exit 0 且 stdout 非空
     7. README 目录树一致   README.md 目录树列出的路径存在，且 references/*.md、scripts/*.py 无遗漏
     8. 示例人格合规        examples/ 下每个目录名以 -persona 结尾、与 name 一致、9 字段齐（`axes` 四轴）、过 fidelity_check
     9. slug 一致性         示例人格 slug 在所有 *.md 里拼写一致（防 skeptic / skeptical 漂移）
     10. 文档 / 脚本契约     roster.py 只读、SKILL.md 不声称脚本没有的能力、点名的 references 存在
     11. CI 存在性          .github/workflows/ci.yml 存在且跑 selfcheck.py 与测试
     12. 常量一致性          四轴分值 / 等级线 / 门槛 / 红线 / 张力门禁在 `_spec.py` 与文档之间一致，
                            且没有别的脚本再硬编码这些数值
     13. 概念重复（指针纪律） 活跃文档之间不得有连续 4 行以上的逐字重复
                            （design-philosophy.md §四：「漂移的根因是复制」）
     14. 声明的脚本行为存在 文档写着「`X.py` 会核 Y」时，X.py 里必须真的能找到 Y 的实现
                            （空头支票会让读者以为有机器在守，而那条纪律就真的没人守了）
     15. 示例哈希声明一致   示例人格文档里写出的 sha256 前缀必须与实际文件对得上
                            （曾出现同一个文件里两个哈希不一致，而 CI 全绿）

检查 1 的解析范围：只认**仓库内**引用。人格目录内的 `references/AXIOMS.md`（相对于
`*-persona/` 解析）不算悬空；**外部链接**（`http(s)://` / 明说「另一个仓库」）也不校验——
**输入是通用的**（`design-philosophy.md` §零）——本仓库既不依赖任何外部 skill 的格式契约，
也不要求用户把材料整理成某种格式，因此**没有单独的输入契约文档**。外部链接只是引用。
规则见 `_ref_ok()`。

检查 5 / 6 的豁免：`scripts/` 下**下划线前缀**的文件是共享模块（`_yaml_subset.py` /
`_material.py`），不是 CLI，不参与 `--help` 与解析器唯一性检查。

检查 2 的豁免范围：射程只到活跃文档（`SKILL.md` / `README.md` / `references/*.md`），
`examples/`（示例产物）整体豁免。活跃文档里，术语出现在
**明确说明「已删除 / 不做 / 不提供 / 曾经 / 迁移 / 已废弃」**的行、其所在表格的引导句、
或其所在小节标题之下时不算违规——那是「迁移表 / 反模式 / 废弃说明」，不是在提供功能。
"""

import difflib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _yaml_subset import (parse_frontmatter, as_dict, as_int, as_str, is_null,
                          sha256_file)  # noqa: E402
from _material import FIELD_SOURCE  # noqa: E402
from _spec import (AXES, AXIS_LETTER, AXIS_REDLINE, GRADE_CUTOFFS,
                   TENSION_MIN_GATE, TENSION_MIN_TARGET, TOTAL_THRESHOLD,
                   make_usage_error)  # noqa: E402

INLINE = re.compile(r"`([^`\n]+)`")
LOCAL_PATH_RE = re.compile(r"(?<![\w/.-])((?:references|scripts|examples)/[A-Za-z0-9._/-]+)")
PERSONA_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*-persona")
SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"})

#: v3.0.0 起失效的术语 —— 活跃文档里只能出现在「已删除 / 不做 / 不提供 / 迁移 / 已废弃」语境
STALE_TERMS = ("四阵型", "阵型", "圆桌", "遣将", "panel", "主持人", "原型型")
STALE_EXEMPT_RE = re.compile(r"(删除|已删除|不做|不提供|曾经|迁移|移除|废弃|弃用)")

#: 「活跃文档」= 受机械契约约束的 markdown；`examples/`（示例产物）不算
ACTIVE_DOCS = ("SKILL.md", "README.md")

#: 四轴（`AXES`）来自 `_spec.py`（唯一实现）——本文件不复制数值常量。

#: 只读脚本：任何 markdown 不得声称它会写文件
READONLY_SCRIPTS = ("roster.py",)
WRITE_CLAIM_RE = re.compile(r"(写入|写出|生成文件|保存到|落盘|--out)")
WRITE_NEGATION_RE = re.compile(r"(不写|只读|不修改|不自动改|只打印|报告|不创建|不生成)")


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

#: 参数错误统一走 stderr + exit 1（实现见 `_spec.make_usage_error`）
usage_error = make_usage_error(
    "用法: python3 selfcheck.py [--root DIR] [--json] [--quiet]")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _iter_md(root):
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for name in sorted(fn):
            if name.endswith(".md"):
                yield os.path.join(dp, name)


def _iter_active_md(root):
    """受活跃契约约束的 markdown。

    `examples/` 是**示例产物**，不受文档契约约束（由「示例人格合规」单独核）。
    """
    for md in _iter_md(root):
        if _rel(root, md).split("/", 1)[0] == "examples":
            continue
        yield md


def _active_doc_paths(root):
    """`ACTIVE_DOCS` + `references/*.md` —— 废弃术语检查的射程。"""
    out = []
    for name in ACTIVE_DOCS:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            out.append(p)
    refs = os.path.join(root, "references")
    if os.path.isdir(refs):
        for name in sorted(os.listdir(refs)):
            p = os.path.join(refs, name)
            if os.path.isfile(p) and name.endswith(".md"):
                out.append(p)
    return out


def _iter_scripts(root):
    d = os.path.join(root, "scripts")
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d))
            if n.endswith(".py") and os.path.isfile(os.path.join(d, n))]


def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _persona_base(root, md_path):
    """若 md 位于某个 `*-persona/` 目录内，返回该目录。"""
    parts = _rel(root, md_path).split("/")
    for i, p in enumerate(parts[:-1]):
        if p.endswith("-persona"):
            return os.path.join(root, *parts[:i + 1])
    return None


def _any_persona_has(root, relpath):
    """是否存在某个示例人格自带的同名文件（如 references/AXIOMS.md）。"""
    ex = os.path.join(root, "examples")
    if not os.path.isdir(ex):
        return False
    for name in os.listdir(ex):
        if name.endswith("-persona") and os.path.exists(os.path.join(ex, name, relpath)):
            return True
    return False


def _ref_ok(root, md_path, line, cand):
    """仓库内引用是否存在。人格目录相对路径 / 跨仓库引用不算悬空。"""
    if os.path.exists(os.path.join(root, cand)):
        return True
    base = _persona_base(root, md_path)
    if base and os.path.exists(os.path.join(base, cand)):
        return True
    if "人格目录" in line or "人格 SKILL.md" in line:
        return True
    # 外部链接（含别的仓库）不算悬空：本仓库不校验外部路径
    if any(k in line for k in ("http://", "https://", "另一个仓库")):
        return True
    if cand == "references/AXIOMS.md" and _any_persona_has(root, cand):
        return True
    return False


def _cands_in_line(line):
    out = []
    for span in INLINE.findall(line):
        for cand in LOCAL_PATH_RE.findall(span):
            cand = cand.rstrip(".,;:)]}」")
            if not cand or "<" in cand or ">" in cand or "*" in cand:
                continue
            out.append(cand)
    return out


def _md_section(text, marker):
    m = re.search(r"^##\s+[^\n]*" + re.escape(marker) + r"[^\n]*\n(.*?)(?=^##\s|\Z)",
                  text, re.M | re.S)
    return m.group(1) if m else None


def _roster_field_issues(fm):
    """→ (missing, warnings)。名册必填字段（合成型以公理集替代 `source_material`，见 persona-forge.md §3.1）。

    v3：`axes`（四轴内联映射）取代 v2 的 `fidelity` / `generativity`；旧字段仍被接受，
    但记一条 ⚠️ 弃用警告（不算 FAIL）。
    源材料字段是 `source_material*`（见 roster-format.md §一）。
    """
    missing = [f for f in ("name", "persona_type", "updated", "triggers", "status")
               if is_null(fm.get(f))]
    if not is_null(fm.get(FIELD_SOURCE)):
        # `source_material_sha256` / `_version` 可选（输入通用，可无文件）
        pass
    elif not is_null(fm.get("source_axioms")):
        if is_null(fm.get("source_axioms_sha256")):
            missing.append("source_axioms_sha256")
    else:
        missing.append("source_material 或 source_axioms")

    warnings = []
    has_axes = not is_null(fm.get("axes"))
    has_legacy = not is_null(fm.get("fidelity"))
    if not has_axes and not has_legacy:
        missing.append("axes")
    elif has_axes:
        axes = as_dict(fm.get("axes"))
        lack = [n for n, _ in AXES if as_int(axes.get(n)) is None]
        if lack:
            missing.append("axes 缺轴：" + "、".join(lack))
    if not has_axes and has_legacy:
        warnings.append("`fidelity` 字段已弃用，请改为 `axes`（四轴）")
    return missing, warnings


# --------------------------------------------------------------------------
# 检查 1：引用文件存在性
# --------------------------------------------------------------------------

def check_referenced_files(root):
    problems = []
    for md in _iter_active_md(root):
        rel = _rel(root, md)
        try:
            text = _read(md)
        except OSError as e:
            problems.append("%s 读取失败: %s" % (rel, e))
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for cand in _cands_in_line(line):
                if not _ref_ok(root, md, line, cand):
                    problems.append("%s:%d 引用 `%s`，磁盘上不存在" % (rel, lineno, cand))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 3：废弃术语（活跃文档不得把已废弃的编排层当作功能描述）
# --------------------------------------------------------------------------

def _enclosing_heading(lines, idx):
    for j in range(idx - 1, -1, -1):
        if lines[j].lstrip().startswith("#"):
            return lines[j]
    return ""


def _governing_lead(lines, idx):
    """表格行之前最近的一行非表格正文——迁移表 / 反模式表的引导句。"""
    for j in range(idx - 1, -1, -1):
        s = lines[j].strip()
        if not s:
            continue
        if s.startswith("|"):
            continue
        if s.startswith("#"):
            return ""
        return lines[j]
    return ""


def check_stale_terminology(root):
    """活跃文档不得把 四阵型 / 圆桌 / 遣将 / panel / 主持人 / 原型型 当作**功能**描述。

    射程：`SKILL.md`、`README.md`、`references/*.md`。`examples/`（示例产物）整体豁免。
    豁免行：明确说明「已删除 / 不做 / 不提供 / 曾经 / 迁移 / 已废弃」的行、
    其所在表格的引导句、或其所在小节标题之下——那是迁移表 / 反模式 / 废弃说明，
    不是在提供功能。
    """
    problems = []
    for md in _active_doc_paths(root):
        rel = _rel(root, md)
        try:
            text = _read(md)
        except OSError as e:
            problems.append("%s 读取失败: %s" % (rel, e))
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            hits = [t for t in STALE_TERMS if t in line]
            if not hits:
                continue
            if STALE_EXEMPT_RE.search(line):
                continue
            if line.strip().startswith("|") and STALE_EXEMPT_RE.search(
                    _governing_lead(lines, idx)):
                continue
            if STALE_EXEMPT_RE.search(_enclosing_heading(lines, idx)):
                continue
            problems.append("%s:%d 出现 v3.0.0 已废弃 / 已弃用的术语 %s：%s"
                            % (rel, idx + 1, "、".join(hits), line.strip()[:70]))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 4：路由表完整性
# --------------------------------------------------------------------------

def check_routing_table(root):
    skill = os.path.join(root, "SKILL.md")
    if not os.path.isfile(skill):
        return False, ["SKILL.md 不存在"]
    text = _read(skill)
    sec = None
    for marker in ("§四", "参考文件路由", "§三"):
        sec = _md_section(text, marker)
        if sec is not None:
            break
    if sec is None:
        return False, ["SKILL.md 未找到路由表（§四 参考文件路由）"]
    problems = []
    for lineno, line in enumerate(sec.splitlines(), 1):
        for cand in _cands_in_line(line):
            if not cand.startswith(("references/", "scripts/")):
                continue
            if not _ref_ok(root, skill, line, cand):
                problems.append("SKILL.md 路由表 第 %d 行点名 `%s`，磁盘上不存在" % (lineno, cand))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 5：canonical source 纪律
# --------------------------------------------------------------------------

def check_canonical_discipline(root):
    dp = os.path.join(root, "references", "design-philosophy.md")
    if not os.path.isfile(dp):
        return False, ["references/design-philosophy.md 不存在"]
    text = _read(dp)
    sec = _md_section(text, "本文件与其他文件的关系")
    if sec is None:
        return False, ["design-philosophy.md 未找到 §四「本文件与其他文件的关系」"]
    problems = []
    for line in sec.splitlines():
        for span in INLINE.findall(line):
            s = span.strip()
            if re.fullmatch(r"references/[A-Za-z0-9._-]+\.md", s):
                if not os.path.exists(os.path.join(root, s)):
                    problems.append("design-philosophy.md §四 点名 `%s`，磁盘上不存在" % s)
            elif re.fullmatch(r"[A-Za-z0-9_-]+\.md", s):
                if not (os.path.exists(os.path.join(root, "references", s))
                        or os.path.exists(os.path.join(root, s))):
                    problems.append("design-philosophy.md §四 点名 `%s`，磁盘上不存在" % s)
    skill = os.path.join(root, "SKILL.md")
    if os.path.isfile(skill) and "references/design-philosophy.md" not in _read(skill):
        problems.append("SKILL.md 未引用 references/design-philosophy.md（单一真相源没被路由到）")
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 4：frontmatter 解析器唯一性
# --------------------------------------------------------------------------

def check_no_duplicate_parsers(root):
    problems = []
    for py in _iter_scripts(root):
        base = os.path.basename(py)
        if base.startswith("_"):
            continue  # 共享模块（_yaml_subset.py / _material.py）不是 CLI
        text = _read(py)
        defines = _dedupe(re.findall(r"^\s*def\s+(parse_frontmatter|parse_scalar)\s*\(", text, re.M))
        imports = re.search(r"from\s+_yaml_subset\s+import|import\s+_yaml_subset", text)
        uses = re.search(r"\bparse_frontmatter\s*\(", text)
        if defines:
            problems.append("%s 自定义了 %s（必须 import _yaml_subset）"
                            % (base, "、".join("`%s`" % d for d in defines)))
        elif uses and not imports:
            problems.append("%s 使用 parse_frontmatter 但未 import _yaml_subset" % base)
    return (not problems), problems


# --------------------------------------------------------------------------
# 检查 5：脚本 --help 支持
# --------------------------------------------------------------------------

def check_script_help(root):
    problems = []
    for py in _iter_scripts(root):
        base = os.path.basename(py)
        if base.startswith("_"):
            continue  # 共享模块不是 CLI，没有 --help
        try:
            r = subprocess.run([sys.executable, py, "--help"],
                               capture_output=True, text=True, timeout=30)
        except Exception as e:  # noqa: BLE001
            problems.append("%s --help 执行失败: %s" % (base, e))
            continue
        if r.returncode != 0:
            problems.append("%s --help 退出码 %d（须为 0）" % (base, r.returncode))
        elif not r.stdout.strip():
            problems.append("%s --help 无 stdout 输出" % base)
    return (not problems), problems


# --------------------------------------------------------------------------
# 检查 6：README 目录树一致
# --------------------------------------------------------------------------

def _parse_tree(tree):
    """→ (repo_name, [列出的相对路径])。"""
    repo_name, listed, stack = None, [], []
    for line in tree.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([\s│]*)(?:├──|└──)\s*(.+?)\s*$", line)
        if not m:
            root_name = line.strip().rstrip("/")
            if root_name:
                repo_name = root_name
                stack = [(-1, root_name)]
            continue
        indent = len(m.group(1))
        name = m.group(2).split("#")[0].strip()
        if not name:
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1] if stack else ""
        path = (parent + "/" + name.rstrip("/")) if parent else name.rstrip("/")
        if name.endswith("/"):
            stack.append((indent, path))
        else:
            listed.append(path)
    return repo_name, listed


def check_readme_tree(root):
    readme = os.path.join(root, "README.md")
    if not os.path.isfile(readme):
        return False, ["README.md 不存在"]
    text = _read(readme)
    m = re.search(r"##\s*目录结构[^\n]*\n+```[a-zA-Z]*\n(.*?)```", text, re.S)
    if not m:
        return False, ["README.md 未找到「目录结构」代码块"]
    repo_name, listed = _parse_tree(m.group(1))
    problems = []
    listed_rel = set()
    for p in listed:
        rel = p[len(repo_name) + 1:] if repo_name and p.startswith(repo_name + "/") else p
        listed_rel.add(rel)
        if not os.path.exists(os.path.join(root, rel)):
            problems.append("README 目录树列出 `%s`，磁盘上不存在" % p)
    for sub in ("references", "scripts"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not os.path.isfile(os.path.join(d, name)):
                continue
            if not (name.endswith(".md") if sub == "references" else name.endswith(".py")):
                continue
            if "%s/%s" % (sub, name) not in listed_rel:
                problems.append("`%s/%s` 未出现在 README 目录树中" % (sub, name))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 7：示例人格合规
# --------------------------------------------------------------------------

def check_example_persona(root):
    exdir = os.path.join(root, "examples")
    if not os.path.isdir(exdir):
        return False, ["examples/ 目录不存在"]
    hard, soft, found = [], [], False
    fc = os.path.join(root, "scripts", "fidelity_check.py")
    for name in sorted(os.listdir(exdir)):
        d = os.path.join(exdir, name)
        if not os.path.isdir(d):
            continue
        found = True
        if not name.endswith("-persona"):
            hard.append("examples/%s 目录名未以 `-persona` 结尾" % name)
        skill = os.path.join(d, "SKILL.md")
        if not os.path.isfile(skill):
            hard.append("examples/%s 缺少 SKILL.md" % name)
            continue
        fm, _body = parse_frontmatter(_read(skill))
        if fm is None:
            hard.append("examples/%s/SKILL.md 无 frontmatter" % name)
            continue
        fmname = as_str(fm.get("name"))
        if fmname != name:
            hard.append("examples/%s 目录名与 frontmatter name（%s）不一致"
                        % (name, fmname if fmname else "缺"))
        missing, warns = _roster_field_issues(fm)
        if missing:
            hard.append("examples/%s 缺名册字段：%s" % (name, "、".join(missing)))
        for w in warns:
            soft.append("examples/%s: %s" % (name, w))
        if os.path.isfile(fc):
            r = subprocess.run([sys.executable, fc, skill],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                hard.append("examples/%s 未通过 fidelity_check.py（退出码 %d）"
                            % (name, r.returncode))
    if not found:
        hard.append("examples/ 下没有任何示例人格目录")
    return (not hard), _dedupe(hard + soft)


# --------------------------------------------------------------------------
# 检查 8：slug 一致性
# --------------------------------------------------------------------------

def check_slug_consistency(root):
    exdir = os.path.join(root, "examples")
    if not os.path.isdir(exdir):
        return False, ["examples/ 目录不存在，无法核对 slug"]
    canonical = [n for n in sorted(os.listdir(exdir))
                 if os.path.isdir(os.path.join(exdir, n)) and n.endswith("-persona")]
    if not canonical:
        return False, ["examples/ 下没有示例人格，无法核对 slug"]
    problems = []
    for md in _iter_active_md(root):
        rel = _rel(root, md)
        try:
            text = _read(md)
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for tok in PERSONA_SLUG_RE.findall(line):
                if tok in canonical:
                    continue
                for c in canonical:
                    if difflib.SequenceMatcher(None, tok, c).ratio() >= 0.85:
                        problems.append("%s:%d 出现 `%s`，与磁盘目录 `%s` 拼写不一致"
                                        % (rel, lineno, tok, c))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 9：文档 / 脚本契约
# --------------------------------------------------------------------------

def _script_help_text(root, script_path):
    try:
        r = subprocess.run([sys.executable, script_path, "--help"],
                           capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return None
    return r.stdout if r.returncode == 0 else None


def check_doc_script_contract(root):
    problems = []
    # 9.1 roster.py 只读：markdown 不得声称它会写文件
    for md in _iter_active_md(root):
        rel = _rel(root, md)
        try:
            text = _read(md)
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if not any(s in line for s in READONLY_SCRIPTS):
                continue
            if WRITE_CLAIM_RE.search(line) and not WRITE_NEGATION_RE.search(line):
                problems.append("%s:%d 声称 `%s` 会写文件（它只读）: %s"
                                % (rel, lineno, "roster.py", line.strip()))

    # 9.2 SKILL.md 不得声称脚本没有的能力
    skill = os.path.join(root, "SKILL.md")
    if not os.path.isfile(skill):
        problems.append("SKILL.md 不存在")
        return (not problems), problems
    text = _read(skill)
    help_cache = {}
    for m in re.finditer(r"scripts/([A-Za-z0-9_]+\.py)([^\n`]*)", text):
        base, tail = m.group(1), m.group(2)
        sp = os.path.join(root, "scripts", base)
        if not os.path.isfile(sp):
            problems.append("SKILL.md 点名 `scripts/%s`，磁盘上不存在" % base)
            continue
        flags = re.findall(r"--[a-z][a-z0-9-]+", tail)
        if not flags:
            continue
        if base not in help_cache:
            help_cache[base] = _script_help_text(root, sp)
        helptext = help_cache[base]
        if helptext is None:
            problems.append("SKILL.md 声称 `scripts/%s` 可用，但它 --help 失败" % base)
            continue
        for fl in flags:
            if fl not in helptext:
                problems.append("SKILL.md 声称 `scripts/%s` 支持 `%s`，但 --help 中无此选项"
                                % (base, fl))

    # 9.3 SKILL.md 点名的每个 references/*.md 都存在
    for lineno, line in enumerate(text.splitlines(), 1):
        for cand in _cands_in_line(line):
            if cand.startswith("references/") and not _ref_ok(root, skill, line, cand):
                problems.append("SKILL.md:%d 点名 `%s`，磁盘上不存在" % (lineno, cand))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 10：CI 存在性
# --------------------------------------------------------------------------

def check_ci_presence(root):
    path = os.path.join(root, ".github", "workflows", "ci.yml")
    if not os.path.isfile(path):
        return False, ["缺少 .github/workflows/ci.yml（CI 未接入，自检不会自动跑）"]
    text = _read(path)
    problems = []
    if "selfcheck.py" not in text:
        problems.append("ci.yml 未运行 `scripts/selfcheck.py`")
    if not re.search(r"test", text, re.I):
        problems.append("ci.yml 未运行测试（未检出 `test`）")
    return (not problems), problems


# --------------------------------------------------------------------------
# 检查 12：常量一致性（四轴分值 / 等级线 / 门槛 / 红线 / 张力门禁）
# --------------------------------------------------------------------------

def check_constant_consistency(root):
    """`_spec.py` 是数值常量的**唯一实现**——文档与其他脚本都不得与之不一致。

    这一项针对的是一类具体的历史故障：四轴满分曾在 4 个脚本 + 4 处文档里各写一遍，
    张力门槛在 5 处文档里是 `≥2`、在评分卡与脚本里是 `≥1`。
    改一次分值要改八处，而没有任何检查会发现漏改。
    """
    problems = []

    # ---- 1) 其他脚本不得再硬编码四轴分值 ----
    for sp in _iter_scripts(root):
        base = os.path.basename(sp)
        if base == "_spec.py":
            continue
        text = _read(sp)
        for name, mx in AXES:
            if re.search(r'["\']%s["\']\s*,\s*%d\b' % (re.escape(name), mx), text):
                problems.append(
                    "scripts/%s 硬编码了四轴分值（`%s`, %d）——应 `from _spec import AXES`"
                    % (base, name, mx))

    # ---- 2) 评分卡：四轴满分表 ----
    sc_path = os.path.join(root, "references", "fidelity-scorecard.md")
    if not os.path.isfile(sc_path):
        problems.append("references/fidelity-scorecard.md 不存在——四轴的 canonical source 缺失")
        return (not problems), problems
    sc = _read(sc_path)
    for name, mx in AXES:
        m = re.search(r"\|\s*\*\*%s\s+[A-Z]\*\*\s*\|\s*\*\*(\d+)\*\*" % re.escape(name), sc)
        if not m:
            problems.append("fidelity-scorecard.md 的轴表里找不到「%s」的满分——格式变了？" % name)
        elif int(m.group(1)) != mx:
            problems.append("fidelity-scorecard.md 说「%s」满分 %s，`_spec.py` 说 %d"
                            % (name, m.group(1), mx))

    # ---- 3) 评分卡：等级线 ----
    for name, floor in GRADE_CUTOFFS:
        m = re.search(r"\|\s*\*\*%s\*\*\s*\|\s*[≥<]?\s*(\d+)" % name, sc)
        if not m:
            problems.append("fidelity-scorecard.md 的等级表里找不到「%s」——格式变了？" % name)
        elif int(m.group(1)) != floor:
            problems.append("fidelity-scorecard.md 说等级 %s 的线是 %s，`_spec.py` 说 %d"
                            % (name, m.group(1), floor))

    # ---- 4) 评分卡：分轴红线 ----
    for axis, red in AXIS_REDLINE.items():
        letter = AXIS_LETTER[axis]
        if red == 0:
            continue          # 溯源 S=0 的写法是 `S = 0`，单独核
        m = re.search(r"%s\s*%s\s*<\s*(\d+)" % (re.escape(axis), letter), sc)
        if not m:
            problems.append("fidelity-scorecard.md 的红线段里找不到「%s %s<…」" % (axis, letter))
        elif int(m.group(1)) != red:
            problems.append("fidelity-scorecard.md 说「%s %s<%s」，`_spec.py` 说 <%d"
                            % (axis, letter, m.group(1), red))
    if not re.search(r"溯源\s*S\s*=\s*0", sc):
        problems.append("fidelity-scorecard.md 的红线段里找不到「溯源 S = 0 → 判 D」")

    # ---- 5) 名册规范：可用门槛 ----
    rf_path = os.path.join(root, "references", "roster-format.md")
    if os.path.isfile(rf_path):
        rf = _read(rf_path)
        m = re.search(r"`total`\s*≥\s*(\d+)", rf)
        if not m:
            problems.append("roster-format.md 里找不到「`total` ≥ N」的门槛表述")
        elif int(m.group(1)) != TOTAL_THRESHOLD:
            problems.append("roster-format.md 说可用门槛是 %s，`_spec.py` 说 %d"
                            % (m.group(1), TOTAL_THRESHOLD))

    # ---- 6) 张力门槛：文档里的数字必须落在 {硬门禁, 质量目标} 内 ----
    allowed = {TENSION_MIN_GATE, TENSION_MIN_TARGET}
    for md in _active_doc_paths(root):
        for lineno, line in enumerate(_read(md).splitlines(), 1):
            for m in re.finditer(r"(?:至少|≥)\s*(\d+)\s*对[^\n]{0,6}张力", line):
                n = int(m.group(1))
                if n not in allowed:
                    problems.append(
                        "%s:%d 说张力门槛是 %d 对，但 `_spec.py` 只允许 %s"
                        % (_rel(root, md), lineno, n, " / ".join(map(str, sorted(allowed)))))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 13：概念重复（`design-philosophy.md` §四 的「指针纪律」）
# --------------------------------------------------------------------------

#: 连续多少行逐字相同才算「复制」（低于此值多为表格表头/分隔行的偶然撞车）
DUP_RUN_MIN = 4

#: 低于此长度的行不参与比对（表头、分隔行、空行）
DUP_LINE_MIN = 8


def _significant_lines(text):
    """→ [(行号, 归一化文本)]，剔除代码块与琐碎行。

    代码块整段跳过：spawn 出去的 prompt **必须内联**（`design-philosophy.md` §四
    的例外条款），那不是漂移，是设计要求。
    """
    out, in_fence = [], False
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if len(s) < DUP_LINE_MIN:
            continue
        if re.match(r"^\|[\s:|-]+\|$", s):      # 表格分隔行
            continue
        out.append((lineno, s))
    return out


def check_no_duplicated_blocks(root):
    """活跃文档之间不得有 `DUP_RUN_MIN` 行以上的**逐字重复**。

    `design-philosophy.md` §四：「**漂移的根因是复制，不是写错。** 任何概念在第二处
    出现时，只能写成指针；写成表格就会漂移。」该节末尾声称
    「`scripts/selfcheck.py` 会机械检查这条纪律」——本检查就是那句话的实现。
    （此前它只是一句声明，没有任何实现，于是 README 与 SKILL.md 真的复制出了两处漂移。）
    """
    docs = []
    for md in _active_doc_paths(root):
        docs.append((_rel(root, md), _significant_lines(_read(md))))

    problems = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            name_a, lines_a = docs[i]
            name_b, lines_b = docs[j]
            index_b = {}
            for k, (_ln, s) in enumerate(lines_b):
                index_b.setdefault(s, []).append(k)
            k = 0
            while k < len(lines_a):
                hits = index_b.get(lines_a[k][1])
                if not hits:
                    k += 1
                    continue
                best = 0
                for h in hits:
                    run = 0
                    while (k + run < len(lines_a) and h + run < len(lines_b)
                           and lines_a[k + run][1] == lines_b[h + run][1]):
                        run += 1
                    best = max(best, run)
                if best >= DUP_RUN_MIN:
                    problems.append(
                        "%s:%d 与 %s:%d 有 %d 行逐字重复 —— 概念只许在 canonical source "
                        "定义一次，第二处写成指针（design-philosophy.md §四）"
                        % (name_a, lines_a[k][0], name_b, lines_b[h][0], best))
                    k += best
                else:
                    k += 1
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 14：文档声称的脚本行为必须真的存在
# --------------------------------------------------------------------------

#: 文档里「某脚本会做 X」的声明 → 该脚本里必须能找到实现。
#: 形状：`(文档路径, 声明的正则, 目标脚本, 实现标记的正则, 人话)`
#:
#: 为什么需要这一项：仓库有三处写着「`X.py` 会核 / 会机械检查 Y」，而实现并不存在。
#: 读者据此以为有机器在守，于是那条纪律真的被违反了（README/SKILL.md 的逐字重复
#: 就是「selfcheck 会机械检查指针纪律」这句空头支票的产物）。
#: 这份清单是**显式的**：新增一句这类声明，就往这里加一行。
CLAIMED_BEHAVIORS = (
    ("references/roster-format.md",
     r"`scripts/selfcheck\.py` 会机械检查「任何文档都不得声称 `roster\.py` 会写文件」",
     "scripts/selfcheck.py", r"roster\.py.*(?:写|生成)|WRITE_CLAIM_RE", "roster 只读声明"),
    ("references/roster-format.md",
     r"`roster\.py` 会报告它的「生效中」条数",
     "scripts/roster.py", r"calib", "校准生效中条数"),
    ("references/persona-template.md",
     r"`scripts/selfcheck\.py` 会机械检查这条纪律",
     "scripts/selfcheck.py", r"def check_no_duplicate_parsers\b", "frontmatter 解析器唯一性"),
    ("references/persona-template.md",
     r"`fidelity_check\.py` 会逐条核",
     "scripts/fidelity_check.py", r"def check_provenance\b", "src: 溯源指针"),
    ("references/persona-template.md",
     r"`roster\.py` 会检测重叠与子串包含",
     "scripts/roster.py", r"def find_conflicts\b", "触发词重叠"),
    ("references/persona-forge.md",
     r"`fidelity_check\.py` 会核",
     "scripts/fidelity_check.py", r"失效条件|失效\|反例", "启发式的失效条件"),
    ("references/design-philosophy.md",
     r"`scripts/selfcheck\.py` 会机械检查这条纪律",
     "scripts/selfcheck.py", r"def check_no_duplicated_blocks\b", "概念重复（指针纪律）"),
)


def check_claimed_behaviors(root):
    """文档说「某脚本会做 X」时，X 必须真的在脚本里。"""
    problems = []
    for doc_rel, claim_re, script_rel, impl_re, label in CLAIMED_BEHAVIORS:
        doc_path = os.path.join(root, doc_rel)
        script_path = os.path.join(root, script_rel)
        if not os.path.isfile(doc_path):
            problems.append("声明登记表里的文档不存在：%s" % doc_rel)
            continue
        if not re.search(claim_re, _read(doc_path)):
            problems.append(
                "%s 里已找不到声明「%s」——声明改了就同步更新 selfcheck 的 CLAIMED_BEHAVIORS"
                % (doc_rel, label))
            continue
        if not os.path.isfile(script_path):
            problems.append("声明登记表里的脚本不存在：%s" % script_rel)
            continue
        if not re.search(impl_re, _read(script_path)):
            problems.append(
                "%s 声称「%s 会做「%s」」，但 %s 里找不到对应实现 —— "
                "要么实现它，要么删掉那句声明（空头支票会让读者以为有机器在守）"
                % (doc_rel, script_rel, label, script_rel))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------
# 检查 15：示例里的 sha256 声明必须与实际文件一致
# --------------------------------------------------------------------------

#: `@ sha256 61dc23…` / `sha256: <hex>` 这类**声明式**哈希（前后 6 位以上十六进制）
SHA_CLAIM_RE = re.compile(r"sha256\s*[:：]?\s*`?\s*([0-9a-fA-F]{6,64})")


def check_hash_claims(root):
    """示例人格文档里写出的 sha256 前缀，必须与实际文件对得上。

    历史教训：`examples/skeptic-cfo-persona/SKILL.md` 的 footer 写着
    `@ sha256 4baf96…`，而 `references/AXIOMS.md` 的真实哈希是 `61dc23b6…`
    （frontmatter 与 `FIDELITY.md` 都是对的）——**同一个文件里两个哈希不一致，CI 全绿**。
    哈希是漂移检测的唯一依据，写错就等于漂移检测失效。
    """
    ex = os.path.join(root, "examples")
    if not os.path.isdir(ex):
        return True, []
    problems = []
    for name in sorted(os.listdir(ex)):
        pdir = os.path.join(ex, name)
        axioms = os.path.join(pdir, "references", "AXIOMS.md")
        if not (name.endswith("-persona") and os.path.isfile(axioms)):
            continue
        try:
            actual = sha256_file(axioms)
        except OSError as e:
            problems.append("%s/references/AXIOMS.md 读取失败: %s" % (name, e))
            continue
        for md in _iter_md(pdir):
            for lineno, line in enumerate(_read(md).splitlines(), 1):
                for claimed in SHA_CLAIM_RE.findall(line):
                    if not actual.startswith(claimed.lower()):
                        problems.append(
                            "%s:%d 声称 sha256 `%s…`，但 references/AXIOMS.md 实际是 `%s…`"
                            % (_rel(root, md), lineno, claimed[:8], actual[:8]))
    return (not problems), _dedupe(problems)


# --------------------------------------------------------------------------

CHECKS = [
    ("引用文件存在性", check_referenced_files),
    ("废弃术语", check_stale_terminology),
    ("路由表完整性", check_routing_table),
    ("canonical source 纪律", check_canonical_discipline),
    ("frontmatter 解析器唯一性", check_no_duplicate_parsers),
    ("脚本 --help 支持", check_script_help),
    ("README 目录树一致", check_readme_tree),
    ("示例人格合规", check_example_persona),
    ("slug 一致性", check_slug_consistency),
    ("文档 / 脚本契约", check_doc_script_contract),
    ("CI 存在性", check_ci_presence),
    ("常量一致性", check_constant_consistency),
    ("概念重复（指针纪律）", check_no_duplicated_blocks),
    ("声明的脚本行为存在", check_claimed_behaviors),
    ("示例哈希声明一致", check_hash_claims),
]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    as_json = quiet = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--root":
            if i + 1 >= len(argv):
                usage_error("--root 缺少目录参数")
            root = argv[i + 1]
            i += 2
            continue
        if a.startswith("--root="):
            root = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--json":
            as_json = True
            i += 1
            continue
        if a == "--quiet":
            quiet = True
            i += 1
            continue
        usage_error("未知选项: " + a)

    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        usage_error("根目录不存在: " + root)

    results = []
    for title, fn in CHECKS:
        try:
            ok, msgs = fn(root)
        except Exception as e:  # noqa: BLE001
            ok, msgs = False, ["检查抛异常: %s: %s" % (type(e).__name__, e)]
        results.append((title, bool(ok), list(msgs or [])))

    passed = sum(1 for _t, ok, _m in results if ok)
    failed = [(t, m) for t, ok, m in results if not ok]
    total = len(results)

    if as_json:
        print(json.dumps({
            "root": root,
            "ok": not failed,
            "passed": passed,
            "total": total,
            "checks": [{"name": t, "ok": ok, "messages": m} for t, ok, m in results],
        }, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    print("拘神.skill 仓库自检: %s" % root)
    print("=" * 64)
    for idx, (title, ok, msgs) in enumerate(results, 1):
        if ok and not msgs:
            status = "✅ PASS"
        elif ok:
            status = "⚠️  WARN"
        else:
            status = "❌ FAIL"
        if quiet and ok and not msgs:
            continue
        print("[%2d/%d] %-22s %s" % (idx, total, title, status))
        for msg in msgs:
            print("        · " + msg)
    print("=" * 64)
    print("结果: %d/%d 通过%s" % (passed, total, " · %d 项失败" % len(failed) if failed else ""))
    if failed:
        print("❌ 有未通过项（CI 应失败）。逐项修复，不要放宽检查。")
        return 1
    print("🎉 仓库自检通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
