#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`selfcheck.py` 自身的回归测试。

**为什么需要这个文件**：`selfcheck.py` 是全仓库唯一被文档反复引用为「机械后盾」的脚本
（至少四处写着「`selfcheck.py` 会机械检查」），但它此前**一个测试都没有**。
一个没有测试的后盾，和没有后盾的区别只在于读者的信心。

这里钉死两类东西：
  1. **它真的在守**——对真实仓库跑一遍必须全绿；
  2. **它真的抓得住**——往临时仓库里植入每一类缺陷，对应的检查必须 FAIL。
     （只测「跑通」不测「抓得住」，正是自检最容易被误以为有效的原因。）

运行：
    python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(ROOT, "scripts")


def run_selfcheck(root, *extra):
    cmd = [sys.executable, os.path.join(SCRIPTS, "selfcheck.py"),
           "--root", root, "--json"] + list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    try:
        data = json.loads(p.stdout)
    except ValueError:
        data = None
    return p.returncode, data, p.stdout + p.stderr


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def clone_repo(dst):
    """把真实仓库拷一份（跳过 .git / __pycache__），供「植入缺陷」测试用。"""
    def ignore(_d, names):
        return [n for n in names if n in (".git", "__pycache__")]
    shutil.copytree(ROOT, dst, ignore=ignore)
    return dst


def failed_checks(data):
    """→ {检查名: [问题…]}，只含 FAIL 项。"""
    if not data:
        return {}
    out = {}
    for item in data.get("checks", []):
        if not item.get("ok"):
            out[item.get("name")] = item.get("messages") or []
    return out


class TestSelfcheckOnRealRepo(unittest.TestCase):
    def test_real_repo_is_green(self):
        """真实仓库必须全绿——否则 CI 是假的。"""
        rc, data, out = run_selfcheck(ROOT)
        self.assertEqual(rc, 0, out)
        self.assertIsNotNone(data, "selfcheck --json 没输出可解析的 JSON")
        self.assertEqual(failed_checks(data), {})

    def test_checks_are_not_silently_missing(self):
        """检查项数量只能增不能减——少一项就说明有人放宽了检查。"""
        _rc, data, _out = run_selfcheck(ROOT)
        names = [c["name"] for c in data["checks"]]
        for must in ("常量一致性", "概念重复（指针纪律）", "声明的脚本行为存在"):
            self.assertIn(must, names)


class TestSelfcheckCatchesDefects(unittest.TestCase):
    """每一类缺陷都要被抓到。植入 → 必须 FAIL → 恢复 → 必须 PASS。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="summon-selfcheck-")
        self.repo = clone_repo(os.path.join(self.tmp, "repo"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plant(self, rel, text):
        write(os.path.join(self.repo, rel), text)

    def test_catches_verbatim_duplication(self):
        """概念重复：两个活跃文档之间出现逐字重复的段落。"""
        block = "\n".join([
            "| # | 公理 | 一句话 | 它裁决什么 |",
            "|---|------|--------|-----------|",
            "| 1 | **认知优先** | 铸的是认知，不是口吻 | **先做什么、重什么** |",
            "| 2 | **先立公理，再推导** | 每条主张可溯源到公理，或可推导 | **有没有根** |",
            "| 3 | **生成力是目的** | 只能复述公理集的人格是失败的 | **能不能长出新东西** |",
            "| 4 | **自洽，但保留张力** | 模型不得互相打架；声明的张力是资产 | **内部立不立得住** |",
        ])
        self._plant("README.md", "# R\n\n" + block + "\n")
        self._plant("SKILL.md", "# S\n\n" + block + "\n")
        rc, data, out = run_selfcheck(self.repo)
        self.assertEqual(rc, 1, out)
        self.assertIn("概念重复（指针纪律）", failed_checks(data))

    def test_ignores_code_fences(self):
        """spawn prompt 必须内联（design-philosophy §四 的例外）——代码块不算重复。"""
        prompt = "\n".join([
            "你的任务：对 <slug>-persona 的 SKILL.md 做溯源对抗审查。你是攻击者，只找问题，不修复。",
            "",
            "你可以读：~/.claude/skills/<slug>-persona/SKILL.md（及其 references/）、",
            "~/.claude/skills/<slug>-persona/references/AXIOMS.md（合成型的公理集）、",
            "~/.claude/skills/<slug>-persona/CALIBRATION.md（若存在；运行侧覆盖层，只许收窄）、",
            "源材料 `MATERIAL.md`（实录型 / 原作型的 ground truth；frontmatter + 正文 + 缺口）。",
        ])
        fenced = "```\n" + prompt + "\n```\n"
        self._plant("README.md", "# R\n\n" + fenced)
        self._plant("SKILL.md", "# S\n\n" + fenced)
        rc, data, out = run_selfcheck(self.repo)
        self.assertNotIn("概念重复（指针纪律）", failed_checks(data), out)

    def test_catches_wrong_axis_max(self):
        """常量一致性：文档里的轴满分与 `_spec.py` 不一致。"""
        path = os.path.join(self.repo, "references", "fidelity-scorecard.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("| **生成力 G** | **30** |", text)
        write(path, text.replace("| **生成力 G** | **30** |", "| **生成力 G** | **20** |"))
        rc, data, out = run_selfcheck(self.repo)
        self.assertEqual(rc, 1, out)
        problems = " ".join(failed_checks(data).get("常量一致性", []))
        self.assertIn("生成力", problems)

    def test_catches_hardcoded_axes_in_script(self):
        """常量一致性：脚本里又硬编码了四轴分值。"""
        self._plant("scripts/rogue.py",
                    'AXES = (("生成力", 30), ("自洽性", 25))\n')
        rc, data, out = run_selfcheck(self.repo)
        self.assertEqual(rc, 1, out)
        problems = " ".join(failed_checks(data).get("常量一致性", []))
        self.assertIn("rogue.py", problems)

    def test_catches_dangling_script_claim(self):
        """声明的脚本行为存在：文档说「X.py 会核 Y」但实现被删掉。"""
        path = os.path.join(self.repo, "scripts", "fidelity_check.py")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("def check_provenance", text)
        write(path, text.replace("def check_provenance", "def check_provenance_removed"))
        rc, data, out = run_selfcheck(self.repo)
        self.assertEqual(rc, 1, out)
        problems = " ".join(failed_checks(data).get("声明的脚本行为存在", []))
        self.assertIn("src: 溯源指针", problems)

    def test_catches_missing_readme_tree_entry(self):
        """README 目录树：新脚本没登记。"""
        self._plant("scripts/another_rogue.py", '"""x"""\n')
        rc, data, out = run_selfcheck(self.repo)
        self.assertEqual(rc, 1, out)
        problems = " ".join(failed_checks(data).get("README 目录树一致", []))
        self.assertIn("another_rogue.py", problems)


class TestSelfcheckQuietAndJson(unittest.TestCase):
    def test_quiet_prints_only_failures(self):
        p = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "selfcheck.py"), "--root", ROOT, "--quiet"],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("✅ PASS", p.stdout)

    def test_json_shape(self):
        _rc, data, _out = run_selfcheck(ROOT)
        self.assertIn("checks", data)
        for item in data["checks"]:
            self.assertIn("name", item)
            self.assertIn("ok", item)


if __name__ == "__main__":
    unittest.main(verbosity=2)
