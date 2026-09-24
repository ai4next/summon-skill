#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · YAML 子集解析器（**唯一实现**）

契约（canonical source：`references/persona-template.md` 的 frontmatter 段）：

    允许：  key: 标量
            key: [行内列表]
            key: {行内映射}
            key:            + 后续 "- 项" 块列表
            key: |          + 缩进块标量（如 description）
    禁止：  锚点别名（& / *）、多行嵌套映射

**为什么这个文件存在**：四个脚本曾各自实现一份 `parse_frontmatter`，它们对
`description: |` 的处理各不相同——有的把缩进正文当成顶层 key，于是正文里的一行
`status: retired` 会**覆盖真正的 status**。复制是漂移的根因，所以解析器只留一份。

**所有脚本必须 `from _yaml_subset import ...`，不得再各自实现。**
`scripts/selfcheck.py` 会机械检查这条纪律。
"""

import os
import re
import sys

#: 视为「空」的标量
NULLS = frozenset({"null", "none", "~", "nil", "-", ""})


def strip_quotes(s):
    """去掉成对的引号。"""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def parse_scalar(val):
    """把一行里的值解析为 list / dict / str。"""
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [strip_quotes(x) for x in inner.split(",") if x.strip()]
    if val.startswith("{") and val.endswith("}"):
        out = {}
        for part in val[1:-1].split(","):
            if ":" in part:
                k, _, v = part.partition(":")
                out[strip_quotes(k)] = strip_quotes(v)
        return out
    return strip_quotes(val)


def parse_frontmatter(text):
    """解析 YAML 子集。返回 `(dict, body)`；无 frontmatter 时返回 `(None, text)`。

    块标量（`|` / `>`）会被完整吃进值里，其缩进正文**不会**被当成顶层 key——
    这是旧实现最危险的一个 bug。
    """
    if not text.lstrip().startswith("---"):
        return None, text
    lead = len(text) - len(text.lstrip())
    rest = text[lead:]
    end = rest.find("\n---", 3)
    if end == -1:
        return None, text

    data, current_key = {}, None
    lines = rest[3:end].splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        # ---- 缩进行：块列表项 / 块列表续行 ----
        if line[:1] in (" ", "\t"):
            s = line.strip()
            cur = data.get(current_key) if current_key else None
            if isinstance(cur, list):
                if s.startswith("- "):
                    cur.append(strip_quotes(s[2:]))
                elif s and cur:
                    cur[-1] = cur[-1] + " " + s
            continue

        if ":" not in line:
            continue

        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()

        # ---- 块标量：吃掉后续所有缩进行 ----
        if val in ("|", ">", "|-", ">-", "|+", ">+"):
            block = []
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    block.append("")
                    i += 1
                    continue
                if nxt[:1] in (" ", "\t"):
                    block.append(nxt.strip())
                    i += 1
                    continue
                break
            while block and not block[-1]:
                block.pop()
            data[key] = "\n".join(block)
            current_key = None
            continue

        if not val:
            data[key] = []
            current_key = key
        else:
            data[key] = parse_scalar(val)
            current_key = None

    return data, rest[end + 4:]


# --------------------------------------------------------------------------
# 类型安全取值：旧脚本满屏 `fm.get(x, [])` 导致的字符级遍历 / 崩溃，
# 根因都是「YAML 合法但类型不符」。统一走下面三个 helper。
# --------------------------------------------------------------------------

def as_list(v):
    """任何值 → list。标量字符串包成单元素列表（**不会**按字符拆开）。"""
    if v is None:
        return []
    if isinstance(v, list):
        return [x for x in v if x is not None]
    if isinstance(v, str):
        s = v.strip()
        return [] if s.lower() in NULLS else [s]
    return [v]


def as_str(v, default=None):
    """任何值 → str 或 default。list / dict 一律回落 default。"""
    if isinstance(v, str):
        return default if v.strip().lower() in NULLS else v
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        return str(v)
    return default


def as_int(v, default=None):
    """任何值 → int 或 default。"""
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v.strip())
        except ValueError:
            return default
    return default


def as_dict(v):
    """任何值 → dict（非映射返回空 dict）。"""
    return v if isinstance(v, dict) else {}


def is_null(v):
    """是否为空值（None / 空串 / null 字面量 / 空列表）。"""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() in NULLS
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def ensure_importable():
    """把本目录加入 sys.path，供 `from _yaml_subset import ...` 使用。

    脚本顶部调用一次即可：
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    return here


def sha256_file(path):
    """文件内容的 sha256（漂移检测用）。"""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path):
    """读 UTF-8 文本。

    解码失败会转成 `OSError` 抛出——这样调用方的 `except OSError` 能统一兜住。
    否则 `UnicodeDecodeError`（`ValueError` 的子类）会穿透所有 `except OSError`，
    让脚本以裸 traceback 崩掉而不是给出一句人话。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise OSError("不是合法的 UTF-8 文本（%s）: %s" % (e.reason, path)) from e


def section(body, *titles, **kw):
    """取 `## <title>` 下的正文，容忍标题后缀（如「## 表达DNA · 🎭 人格层」）。

    `titles` 按顺序尝试；`prefix=True` 时改为**子串/前缀匹配**，用于容忍
    「## 02 流派分歧」这类带编号的标题。
    """
    prefix = kw.get("prefix", False)
    for t in titles:
        pat = re.escape(t) if not prefix else r"[^\n]*" + re.escape(t)
        m = re.search(
            r"^##\s+" + pat + r"(?:[ \t]*[·:：—\-|/][^\n]*)?[ \t]*$(.*?)(?=^##\s|\Z)",
            body, re.M | re.S)
        if m:
            return m.group(1)
    return None
