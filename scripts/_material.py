#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拘神.skill · 源材料处理的共享实现（唯一实现，供各脚本 import）

**输入没有格式要求。** 用户给什么，本 skill 就读什么——粘贴文本、任意文件、任意目录、
一份文献、一部原作都可以（上位原则：`design-philosophy.md` §零）。

**可选约定**（只为让漂移检测能工作；不这样做也完全可以）:
    <source-dir>/<slug>/              # 默认 <source-dir> = ./material
    ├── MATERIAL.md                   # 脚本**优先识别**的 ground truth 文件名
    ├── manifest.json                 # 可选：{"material_sha256": "...", "version": N}
    └── QUALITY.md                    # 可选：素材质量等级

    找不到 ground truth 文件**不算错**——只是漂移检测报 `none`。

人格 `SKILL.md` 的 frontmatter 里指向来源的三个字段（后两个可选）:
    source_material          来源描述（自由文本：slug / 路径 / 书名 / 口述日期）
    source_material_sha256   可选；有稳定本地文件时记录，作为漂移依据
    source_material_version  可选；材料的 version

人读的说明见 `roster-format.md` §一。
"""

import json
import os

from _yaml_subset import as_dict, as_int, as_str, read_text, sha256_file

#: ground truth 文件名（脚本**优先识别**，不是要求——任意文件名都可以）
MATERIAL_FILENAME = "MATERIAL.md"
MANIFEST_FILENAME = "manifest.json"
QUALITY_FILENAME = "QUALITY.md"

#: 源材料根目录默认值
SOURCE_DIR_DEFAULT = "material"

#: 人格 frontmatter 里的源材料字段
FIELD_SOURCE = "source_material"
FIELD_SHA256 = "source_material_sha256"
FIELD_VERSION = "source_material_version"

#: 源材料目录的识别标记 —— 出现任一即说明「这是材料目录，不是人格目录」。
#: 写权限护栏用：`calibrate.py` / `feedback_log.py` 拒绝写进这样的目录。
MATERIAL_MARKERS = (MATERIAL_FILENAME, MANIFEST_FILENAME, QUALITY_FILENAME)


def material_path(source_root, slug):
    """→ ground truth 文件路径；找不到 → `None`。**任意文件名都可以。**

    查找顺序（canonical source：`roster-format.md` §一）：
      1. `<source-root>/<slug>/MATERIAL.md`——脚本**优先识别**的名字（不是要求）
      2. 同目录里**唯一**的那个 `.md`
      3. `slug` 本身就是一条文件路径时（`source_material` 是自由文本），直接用
      4. 再按 cwd 试一次（铸造时可能记下的是相对路径）

    **输入是通用的，找不到文件不算错**——只是这个人的漂移检测会报 `none`。
    """
    d = os.path.join(source_root, slug)
    if os.path.isdir(d):
        p = os.path.join(d, MATERIAL_FILENAME)
        if os.path.isfile(p):
            return p
        try:
            mds = sorted(n for n in os.listdir(d) if n.endswith(".md"))
        except OSError:
            mds = []
        if len(mds) == 1:
            return os.path.join(d, mds[0])
        return None
    if os.path.isfile(d):
        return d
    if os.path.isfile(slug):
        return slug
    return None


def manifest_data(source_root, slug):
    """→ manifest.json 解析出的 dict（不存在 / 坏了 → `{}`）。"""
    mpath = os.path.join(source_root, slug, MANIFEST_FILENAME)
    if not os.path.isfile(mpath):
        return {}
    try:
        return as_dict(json.loads(read_text(mpath))) or {}
    except (OSError, ValueError):
        return {}


def material_sha(source_root, slug):
    """→ ground truth 的 sha256；文件找不到时回退 `manifest.json`；都没有 → `None`。"""
    path = material_path(source_root, slug)
    if path:
        return sha256_file(path)
    return as_str(manifest_data(source_root, slug).get("material_sha256")) or None


def material_version(source_root, slug):
    """→ manifest.json 里的 `version`（没有 → `None`）。"""
    return as_int(manifest_data(source_root, slug).get("version"))
