#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`scripts/_yaml_subset.py` 的单元测试。

运行：
    python3 -m unittest discover -s tests -v

为什么这个测试重要：**四个脚本曾各自实现一份 frontmatter 解析器**，
它们对 `description: |` 的处理不一致——最严重的一种会把块标量正文里的
`status: retired` 当成顶层 key，从而**覆盖真正的 status**。
本文件把这个回归钉死。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from _yaml_subset import (  # noqa: E402
    as_dict, as_int, as_list, as_str, is_null, parse_frontmatter, parse_scalar,
    section, strip_quotes,
)


class TestParseScalar(unittest.TestCase):
    def test_plain_scalar(self):
        self.assertEqual(parse_scalar("munger"), "munger")

    def test_quoted_scalar(self):
        self.assertEqual(parse_scalar('"a: b"'), "a: b")
        self.assertEqual(parse_scalar("'x'"), "x")

    def test_inline_list(self):
        self.assertEqual(parse_scalar("[a, b, c]"), ["a", "b", "c"])
        self.assertEqual(parse_scalar("[]"), [])
        self.assertEqual(parse_scalar("[ a , b ]"), ["a", "b"])

    def test_inline_map(self):
        self.assertEqual(
            parse_scalar("{total: 88, grade: A, mode: full}"),
            {"total": "88", "grade": "A", "mode": "full"},
        )

    def test_numeric_looking_stays_string(self):
        # 解析器不猜类型；调用方用 as_int 转换
        self.assertEqual(parse_scalar("88"), "88")

    def test_strip_quotes(self):
        self.assertEqual(strip_quotes("'x'"), "x")
        self.assertEqual(strip_quotes('"x"'), "x")
        self.assertEqual(strip_quotes("x"), "x")
        self.assertEqual(strip_quotes("'"), "'")


class TestParseFrontmatter(unittest.TestCase):
    def test_no_frontmatter(self):
        fm, body = parse_frontmatter("# hi\n")
        self.assertIsNone(fm)
        self.assertEqual(body, "# hi\n")

    def test_simple(self):
        fm, body = parse_frontmatter("---\nname: a-persona\nstatus: active\n---\nbody\n")
        self.assertEqual(fm["name"], "a-persona")
        self.assertEqual(fm["status"], "active")
        self.assertIn("body", body)

    def test_block_scalar_does_not_leak_keys(self):
        """回归：块标量正文里的 `status: retired` 绝不能覆盖真正的 status。"""
        text = (
            "---\n"
            "name: a-persona\n"
            "status: active\n"
            "description: |\n"
            "  第一行说明。\n"
            "  triggers: [injected]\n"
            "  status: retired\n"
            "persona_type: real\n"
            "---\n"
            "body\n"
        )
        fm, _ = parse_frontmatter(text)
        self.assertEqual(fm["status"], "active", "块标量正文覆盖了真正的 status")
        self.assertEqual(fm["persona_type"], "real")
        self.assertIn("第一行说明。", fm["description"])
        self.assertIn("status: retired", fm["description"])
        # 正文里的假 key 不得成为顶层 key
        self.assertNotEqual(fm.get("triggers"), "[injected]")

    def test_block_scalar_then_real_keys(self):
        text = (
            "---\n"
            "description: |\n"
            "  多行\n"
            "  描述\n"
            "triggers: [a, b]\n"
            "status: draft\n"
            "---\n"
        )
        fm, _ = parse_frontmatter(text)
        self.assertEqual(fm["description"], "多行\n描述")
        self.assertEqual(fm["triggers"], ["a", "b"])
        self.assertEqual(fm["status"], "draft")

    def test_block_list(self):
        text = "---\ngaps:\n  - 缺口一\n  - 缺口二\nname: x-persona\n---\n"
        fm, _ = parse_frontmatter(text)
        self.assertEqual(fm["gaps"], ["缺口一", "缺口二"])
        self.assertEqual(fm["name"], "x-persona")

    def test_empty_key_becomes_empty_list(self):
        fm, _ = parse_frontmatter("---\ngaps:\nname: x\n---\n")
        self.assertEqual(fm["gaps"], [])
        self.assertEqual(fm["name"], "x")

    def test_inline_map_value(self):
        fm, _ = parse_frontmatter(
            "---\nfidelity: {total: 88, grade: A, mode: full, date: 2026-09-22}\n---\n")
        self.assertEqual(fm["fidelity"]["total"], "88")
        self.assertEqual(fm["fidelity"]["mode"], "full")

    def test_null_literals(self):
        fm, _ = parse_frontmatter("---\nsource_material: null\n---\n")
        self.assertEqual(as_str(fm["source_material"]), None)

    def test_comments_ignored(self):
        fm, _ = parse_frontmatter("---\n# comment\nname: x\n---\n")
        self.assertEqual(fm["name"], "x")

    def test_realistic_persona_frontmatter(self):
        text = (
            "---\n"
            "schema_version: 2\n"
            "name: skeptic-cfo-persona\n"
            "description: |\n"
            "  怀疑论 CFO。\n"
            "  用途：财务压力测试。\n"
            "persona_type: archetype\n"
            "source_axioms: skeptic-cfo\n"
            "fidelity: {total: 82, grade: B, mode: full, date: 2026-09-22}\n"
            "triggers: [用CFO的视角, 财务视角看看]\n"
            "status: active\n"
            "---\n"
            "# 怀疑论 CFO\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm["schema_version"], "2")
        self.assertEqual(fm["name"], "skeptic-cfo-persona")
        self.assertEqual(fm["persona_type"], "archetype")
        self.assertEqual(fm["status"], "active")
        self.assertEqual(fm["triggers"], ["用CFO的视角", "财务视角看看"])
        self.assertIn("怀疑论 CFO。", fm["description"])
        self.assertIn("用途：财务压力测试。", fm["description"])
        self.assertIn("# 怀疑论 CFO", body)


class TestTypeHelpers(unittest.TestCase):
    def test_as_list_scalar_is_wrapped_not_split(self):
        """回归：`gaps: not-a-list` 曾被逐字符拆成 10 个假缺口。"""
        self.assertEqual(as_list("not-a-list"), ["not-a-list"])
        self.assertEqual(len(as_list("not-a-list")), 1)

    def test_as_list_variants(self):
        self.assertEqual(as_list(None), [])
        self.assertEqual(as_list(""), [])
        self.assertEqual(as_list("null"), [])
        self.assertEqual(as_list(["a"]), ["a"])
        self.assertEqual(as_list(5), [5])

    def test_as_str(self):
        self.assertEqual(as_str("x"), "x")
        self.assertEqual(as_str(None), None)
        self.assertEqual(as_str(""), None)
        self.assertEqual(as_str("null"), None)
        self.assertEqual(as_str(["a"]), None)
        self.assertEqual(as_str(7), "7")
        self.assertEqual(as_str(None, "—"), "—")

    def test_as_int(self):
        self.assertEqual(as_int("88"), 88)
        self.assertEqual(as_int(88), 88)
        self.assertEqual(as_int(88.9), 88)
        self.assertEqual(as_int("x"), None)
        self.assertEqual(as_int("x", 0), 0)
        self.assertEqual(as_int(None), None)
        self.assertEqual(as_int(True), None, "bool 不是 int")

    def test_as_dict(self):
        self.assertEqual(as_dict({"a": 1}), {"a": 1})
        self.assertEqual(as_dict("high"), {})
        self.assertEqual(as_dict(None), {})

    def test_is_null(self):
        for v in (None, "", "null", "~", [], {}):
            self.assertTrue(is_null(v), v)
        for v in ("x", ["a"], {"a": 1}, 0):
            self.assertFalse(is_null(v), v)


class TestSection(unittest.TestCase):
    BODY = (
        "## 核心心智模型 · 🧠 认知层\n"
        "模型正文\n"
        "## 表达DNA\n"
        "风格正文\n"
        "## 诚实边界 · ⚖️ 运行层\n"
        "边界正文\n"
    )

    def test_exact_with_layer_suffix(self):
        self.assertIn("模型正文", section(self.BODY, "核心心智模型"))
        self.assertIn("风格正文", section(self.BODY, "表达DNA"))

    def test_alias_fallback_order(self):
        self.assertIn("模型正文", section(self.BODY, "不存在", "核心心智模型"))

    def test_missing(self):
        self.assertIsNone(section(self.BODY, "没有这一段"))

    def test_prefix_matching_for_numbered_headings(self):
        body = "## 02 流派分歧\n分歧正文\n## 别段\nx\n"
        self.assertIn("分歧正文", section(body, "流派分歧", prefix=True))
        self.assertIsNone(section(body, "流派分歧"))

    def test_stops_at_next_h2(self):
        sec = section(self.BODY, "核心心智模型")
        self.assertNotIn("风格正文", sec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
