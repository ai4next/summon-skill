#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脚本级回归测试：把审计发现的每一个缺陷钉死。

运行：
    python3 -m unittest discover -s tests -v

纪律：**绝不写真实的 `~/.claude/`**——所有 fixture 都在 `tempfile` 下。
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

#: v3 四轴默认 fixture（四个数刻意**不等于**总分，防脚本偷偷相加）
DEFAULT_AXES = {"生成力": 20, "自洽性": 18, "辨识度": 12, "溯源": 15}
DEFAULT_TOTAL = 82
DEFAULT_AXES_FM = ("axes: {生成力: 20, 自洽性: 18, 辨识度: 12, 溯源: 15, "
                   "total: 82, grade: B, mode: full, date: 2026-09-22}\n")
LEGACY_FM = ("fidelity: {total: 80, grade: B, mode: full, date: 2026-09-22}\n"
             "generativity: {total: 13, probes: 2, date: 2026-09-22}\n")


def run(script, *args, **kw):
    """跑一个脚本，返回 (returncode, stdout, stderr)。"""
    cmd = [sys.executable, os.path.join(SCRIPTS, script)] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=kw.get("cwd", ROOT))
    return p.returncode, p.stdout, p.stderr


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def parse_fm(path):
    sys.path.insert(0, SCRIPTS)
    from _yaml_subset import parse_frontmatter
    return parse_frontmatter(read(path))


def make_material(root, slug, body_models="### 能力圈\nx\n### 逆向思考\ny\n",
                 extra_fm="gaps:\n  - 缺口一\n", confidence="confidence: {A: 8, B: 2, C: 1, D: 1}\n"):
    p = os.path.join(root, "material", slug, "MATERIAL.md")
    write(p, "---\nslug: %s\ntitle: %s\nversion: 2\nupdated: 2026-08-01\n%s%s---\n\n"
             "## 心智模型 / 核心骨架\n\n%s\n" % (slug, slug, extra_fm, confidence, body_models))
    return p


def make_persona(root, slug, status="active", triggers="[专属词]", fidelity_md=None,
                 axes_fm=DEFAULT_AXES_FM, material_sha=None, name=None,
                 legacy_fidelity=False):
    d = os.path.join(root, "skills", slug)
    fm = ("---\nschema_version: 2\nname: %s\npersona_type: real\nsource_material: %s\n"
          % (name or slug, slug))
    if material_sha:
        fm += "source_material_sha256: %s\nsource_material_version: 2\n" % material_sha
    fm += "status: %s\nupdated: 2026-09-22\ntriggers: %s\n" % (status, triggers)
    if legacy_fidelity:
        fm += LEGACY_FM
    elif axes_fm:
        fm += axes_fm
    fm += "description: |\n  %s 的人格运行体。\n---\n# %s\n" % (slug, slug)
    write(os.path.join(d, "SKILL.md"), fm)
    if fidelity_md:
        write(os.path.join(d, "FIDELITY.md"), fidelity_md)
    return d


def sha256_of(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="summon-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- forge_scaffold

class TestForgeScaffold(Base):
    def test_help_at_any_position(self):
        for args in (["--help"], ["x.md", "--help"], ["--out", "y", "--help"]):
            rc, out, _ = run("forge_scaffold.py", *args)
            self.assertEqual(rc, 0, args)
            self.assertIn("铸人格脚手架", out)

    def test_models_come_from_core_skeleton_only(self):
        """回归 F4：曾找「核心框架」，落空后把全文 ### 都当模型。"""
        src = make_material(self.tmp, "m", body_models="### 能力圈\nx\n### 逆向思考\ny\n")
        with open(src, "a", encoding="utf-8") as f:
            f.write("\n## 表达特征\n\n### 口癖：短句\n不该被当成模型\n")
        out = os.path.join(self.tmp, "skills", "m-persona")
        rc, so, se = run("forge_scaffold.py", src, "--out", out, "--type", "real")
        self.assertEqual(rc, 0, se)
        text = read(os.path.join(out, "SKILL.md"))
        self.assertIn("### 模型1: 能力圈", text)
        self.assertIn("### 模型2: 逆向思考", text)
        self.assertNotIn("口癖：短句", text)

    def test_scalar_gaps_not_char_split(self):
        """回归 F2：`gaps: not-a-list` 曾被逐字符拆成 10 个假缺口。"""
        p = os.path.join(self.tmp, "material", "g", "MATERIAL.md")
        write(p, "---\nslug: g\ntitle: g\ngaps: not-a-list\n---\n## 心智模型 / 核心骨架\n### m\nx\n")
        out = os.path.join(self.tmp, "skills", "g-persona")
        rc, so, se = run("forge_scaffold.py", p, "--out", out)
        self.assertEqual(rc, 0, se)
        self.assertIn("1 条 gaps", so)
        text = read(os.path.join(out, "SKILL.md"))
        self.assertIn("- not-a-list", text)
        self.assertNotIn("- n\n", text)

    def test_scalar_confidence_does_not_crash(self):
        """回归 F1：`confidence: high` 曾 AttributeError。"""
        p = os.path.join(self.tmp, "material", "c", "MATERIAL.md")
        write(p, "---\nslug: c\ntitle: c\nconfidence: high\ngaps: []\n---\n"
                 "## 心智模型 / 核心骨架\n### m\nx\n")
        rc, so, se = run("forge_scaffold.py", p, "--out", os.path.join(self.tmp, "skills", "c-persona"))
        self.assertEqual(rc, 0, se)
        self.assertNotIn("Traceback", se)

    def test_missing_confidence_reports_unknown_not_zero(self):
        """回归 F3：无 confidence 时曾谎报「一手占比 0%」。"""
        p = os.path.join(self.tmp, "material", "n", "MATERIAL.md")
        write(p, "---\nslug: n\ntitle: n\ngaps: []\n---\n## 心智模型 / 核心骨架\n### m\nx\n")
        out = os.path.join(self.tmp, "skills", "n-persona")
        run("forge_scaffold.py", p, "--out", out)
        text = read(os.path.join(out, "SKILL.md"))
        self.assertIn("一手占比 ?%", text)
        self.assertNotIn("一手占比 0%", text)

    def test_placeholder_triggers_are_empty(self):
        """回归 F8：占位 triggers 会让两个人格误报触发词冲突。"""
        src = make_material(self.tmp, "t1")
        out = os.path.join(self.tmp, "skills", "t1-persona")
        run("forge_scaffold.py", src, "--out", out)
        text = read(os.path.join(out, "SKILL.md"))
        trig_lines = [l for l in text.splitlines() if l.startswith("triggers:")]
        self.assertEqual(trig_lines, ["triggers: []"],
                         "骨架的 triggers 必须是空列表（占位符会导致误报冲突）")

    def test_frontmatter_roundtrips(self):
        """回归 F5：块标量正文不得覆盖真正的 key。"""
        src = make_material(self.tmp, "rt")
        out = os.path.join(self.tmp, "skills", "rt-persona")
        run("forge_scaffold.py", src, "--out", out)
        fm, _ = parse_fm(os.path.join(out, "SKILL.md"))
        self.assertEqual(fm["name"], "rt-persona")
        self.assertEqual(fm["status"], "draft")
        self.assertEqual(fm["triggers"], [])
        self.assertEqual(fm["schema_version"], "2")
        self.assertIn("人格运行体", str(fm["description"]))
        self.assertNotEqual(fm["description"], "|")

    def test_skeleton_emits_axes_not_fidelity(self):
        """v3：骨架 frontmatter 用 `axes`（四轴），不再有 fidelity / generativity。"""
        src = make_material(self.tmp, "ax")
        out = os.path.join(self.tmp, "skills", "ax-persona")
        rc, so, se = run("forge_scaffold.py", src, "--out", out)
        self.assertEqual(rc, 0, se)
        fm, body = parse_fm(os.path.join(out, "SKILL.md"))
        self.assertIsInstance(fm.get("axes"), dict)
        for k in ("生成力", "自洽性", "辨识度", "溯源"):
            self.assertIn(k, fm["axes"])
        self.assertIsNone(fm.get("fidelity"))
        self.assertIsNone(fm.get("generativity"))
        # 已删除的编排层术语不得出现在骨架里
        self.assertNotIn("圆桌", body)
        self.assertNotIn("召唤", body)
        # 诚实边界必须区分「信息缺口」与「闭包边界」
        self.assertIn("信息缺口", body)
        self.assertIn("闭包边界", body)

    def test_src_provenance_placeholders(self):
        """公理 2：骨架必须预置 src: 行。"""
        src = make_material(self.tmp, "sp")
        out = os.path.join(self.tmp, "skills", "sp-persona")
        run("forge_scaffold.py", src, "--out", out)
        text = read(os.path.join(out, "SKILL.md"))
        self.assertGreaterEqual(text.count("- **src**:"), 3)

    def test_axioms_mode(self):
        """persona-forge §七：合成型走 AXIOMS.md（主路径）。"""
        ax = os.path.join(self.tmp, "proj", "skeptic-cfo-persona", "references", "AXIOMS.md")
        write(ax, "# 立场公理集 · 测试\n\n| # | 公理 | 为什么 |\n|---|---|---|\n"
                  "| **A1** | **现金为王** | 终点 |\n| **A2** | **单位经济学** | 终点 |\n")
        out = os.path.join(self.tmp, "skills", "skeptic-cfo-persona")
        rc, so, se = run("forge_scaffold.py", "--axioms", ax, "--out", out)
        self.assertEqual(rc, 0, se)
        fm, body = parse_fm(os.path.join(out, "SKILL.md"))
        self.assertEqual(fm["persona_type"], "archetype")
        self.assertEqual(fm["source_axioms"], "references/AXIOMS.md")
        self.assertEqual(fm["source_axioms_sha256"], sha256_of(ax))
        self.assertIsNone(fm.get("source_material"))
        self.assertIn("不对应任何具体个人", body)
        self.assertIn("闭包边界", body)
        self.assertEqual(body.count("### 模型"), 2)
        # 人格目录必须自包含：公理集被复制进来，哈希取自副本
        copied = os.path.join(out, "references", "AXIOMS.md")
        self.assertTrue(os.path.isfile(copied), "公理集应被复制进人格目录")
        self.assertEqual(fm["source_axioms_sha256"], sha256_of(copied))

    def test_refuses_both_sources_and_file_out(self):
        src = make_material(self.tmp, "r")
        rc, _, _ = run("forge_scaffold.py", src, "--axioms", "x", "--out", self.tmp)
        self.assertEqual(rc, 1)
        afile = os.path.join(self.tmp, "afile")
        write(afile, "x")
        rc, _, se = run("forge_scaffold.py", src, "--out", afile)
        self.assertEqual(rc, 1)
        self.assertNotIn("Traceback", se)

    def test_no_source_is_error(self):
        rc, _, se = run("forge_scaffold.py", "--out", self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("ground truth", se)


# ----------------------------------------------------------------------- roster

class TestRoster(Base):
    #: v3 四轴表头（`fidelity-scorecard.md` §七）
    NEW = ("# 质检评分卡\n\n"
           "**生成力 G：23/30** ｜ **自洽性 C：22/25** ｜ **辨识度 D：17/20** ｜ **溯源 S：20/25**\n"
           "**总分：82/100 · 等级B** ｜ **mode**：full\n")
    #: v2 两轴（向后兼容：F + G/20）
    OLD_TWO_AXIS = ("# 保真度评分卡\n\n**保真度 F：88/100 · 等级A** ｜ "
                    "**生成力 G：15/20**\n**mode**：full\n")
    #: v1 总分
    OLD = "# 保真度评分卡\n\n**总分：88/100 · 等级A**\n"

    def _setup(self, fidelity_md, **kw):
        src = make_material(self.tmp, "p")
        make_persona(self.tmp, "p-persona", fidelity_md=fidelity_md,
                     material_sha=sha256_of(src), **kw)
        return src

    def _run(self):
        return run("roster.py", "--skills-dir", os.path.join(self.tmp, "skills"),
                   "--source-dir", os.path.join(self.tmp, "material"))

    def test_reads_four_axis_header(self):
        """v3：从 FIDELITY.md 表头解析四轴四个数 + 总分 + 等级。"""
        self._setup(self.NEW, legacy_fidelity=True)   # 无 axes 缓存 → 只能读 FIDELITY.md
        rc, so, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("G23 C22 D17 S20", so)          # 名册「四轴」列 = 四个分数
        self.assertIn("总分 82/100 (B)", so)           # 总分与等级在四轴明细段
        for frag in ("生成力 23/30", "自洽性 22/25", "辨识度 17/20", "溯源 20/25"):
            self.assertIn(frag, so)
        self.assertNotIn("四轴 未测", so)

    def test_reads_legacy_two_axis_header(self):
        """向后兼容：`**保真度 F：88/100 · 等级A**` + `**生成力 G：15/20**`。"""
        self._setup(self.OLD_TWO_AXIS, legacy_fidelity=True)
        rc, so, _ = self._run()
        self.assertIn("总分 88/100 (A)", so)
        self.assertIn("旧格式 生成力 G 15/20", so)

    def test_reads_old_total_header(self):
        """向后兼容：v1 `**总分：88/100 · 等级A**`。"""
        self._setup(self.OLD, legacy_fidelity=True)
        rc, so, _ = self._run()
        self.assertIn("总分 88/100 (A)", so)

    def test_axes_frontmatter_used_when_fidelity_missing(self):
        """frontmatter `axes` 缓存可在 FIDELITY.md 缺失时提供四轴（不是降级）。"""
        src = make_material(self.tmp, "p")
        make_persona(self.tmp, "p-persona", material_sha=sha256_of(src))   # 无 FIDELITY.md
        rc, so, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("G20 C18 D12 S15", so)
        self.assertIn("总分 82/100 (B)", so)
        self.assertNotIn("未跑质检评分卡", so)

    def test_fidelity_md_wins_over_axes_cache(self):
        """roster-format.md §三：轴分以 `FIDELITY.md` 为准，`axes` 缓存只补缺轴。"""
        self._setup(self.NEW)   # frontmatter axes = G20 C18 D12 S15；FIDELITY.md = G23 C22 D17 S20
        rc, so, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("G23 C22 D17 S20", so)
        self.assertNotIn("G20 C18 D12 S15", so)

    def test_legacy_fidelity_field_warns_deprecation(self):
        """v3：`fidelity` 字段已弃用，接受但告警。"""
        self._setup(self.NEW, legacy_fidelity=True)
        rc, so, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("`fidelity` 字段已弃用", so)
        self.assertIn("axes", so)

    def test_no_panel_section(self):
        """v3.0.0：panel 支持已删除——名册不得再打印「人格组」段。"""
        self._setup(self.NEW)
        # 即使磁盘上存在 panels/ 与 .panel.md，也不得出现在输出里
        write(os.path.join(self.tmp, "skills", "panels", "x.panel.md"),
              "---\npanel: x\nmembers: [p-persona]\nformations: [roundtable]\n---\n"
              "## agenda\n### 争点\n- **issue**：甲\n- **sides**：p-persona → 是\n")
        rc, so, _ = self._run()
        self.assertEqual(rc, 0)
        for frag in ("人格组", "panel", "阵型", "formations", "agenda", "圆桌"):
            self.assertNotIn(frag, so)

    def test_incoherent_counts_as_defect(self):
        """v3：`incoherent` 属人格缺陷；`faithful_silence` 不计入。"""
        self._setup(self.NEW)
        fb = os.path.join(self.tmp, "skills", "p-persona", "FEEDBACK.jsonl")
        write(fb, json.dumps({"failure": "incoherent"}) + "\n"
                  + json.dumps({"failure": "faithful_silence"}) + "\n")
        rc, so, se = self._run()
        self.assertEqual(rc, 0, se)
        self.assertIn("人格缺陷 1 条", so)
        self.assertIn("忠实沉默 1 条", so)

    def test_survives_non_object_json_lines(self):
        """回归 R1：FEEDBACK.jsonl 里一行 `123` 曾让 roster 崩掉。"""
        self._setup(self.NEW)
        fb = os.path.join(self.tmp, "skills", "p-persona", "FEEDBACK.jsonl")
        write(fb, "123\n" + json.dumps({"failure": "style_drift"}) + "\n")
        rc, so, se = self._run()
        self.assertEqual(rc, 0, se)
        self.assertNotIn("Traceback", se)

    def test_substring_trigger_overlap_detected(self):
        """回归 R8：子串重叠（「芒格」⊂「用芒格的视角」）曾检不出。"""
        src = make_material(self.tmp, "p")
        make_persona(self.tmp, "p-persona", triggers="[芒格]", material_sha=sha256_of(src))
        src2 = make_material(self.tmp, "q")
        make_persona(self.tmp, "q-persona", triggers="[用芒格的视角]", material_sha=sha256_of(src2))
        rc, so, _ = self._run()
        self.assertIn("芒格", so)
        self.assertTrue("包含" in so or "子串" in so or "重叠" in so)

    def test_writes_nothing(self):
        """契约：roster.py 只读不写。"""
        self._setup(self.NEW)
        before = {}
        for dp, _, fs in os.walk(self.tmp):
            for f in fs:
                fp = os.path.join(dp, f)
                before[fp] = os.path.getmtime(fp)
        self._run()
        after = {}
        for dp, _, fs in os.walk(self.tmp):
            for f in fs:
                fp = os.path.join(dp, f)
                after[fp] = os.path.getmtime(fp)
        self.assertEqual(before, after)


# ------------------------------------------------------------------ feedback_log

class TestFeedbackLog(Base):
    def _persona(self):
        d = os.path.join(self.tmp, "p-persona")
        write(os.path.join(d, "SKILL.md"), "---\nname: p-persona\n---\n# p\n")
        return d

    def _last(self, d):
        return json.loads(read(os.path.join(d, "FEEDBACK.jsonl")).splitlines()[-1])

    def test_evidence_without_value_is_refused(self):
        """回归 B1：`--evidence` 无值曾写成 JSON true，绕过「无证据不写入」。"""
        d = self._persona()
        rc, _, _ = run("feedback_log.py", "--persona-dir", d, "--failure", "in_scope_gap",
                       "--question", "q", "--evidence")
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(d, "FEEDBACK.jsonl")))

    def test_policy_gap_accepted(self):
        """回归 B8：policy_gap 曾被拒。"""
        d = self._persona()
        rc, _, se = run("feedback_log.py", "--persona-dir", d, "--failure", "policy_gap",
                        "--question", "q", "--evidence", "档案 §1",
                        "--material-sha", "abc", "--context", "review")
        self.assertEqual(rc, 0, se)
        rec = self._last(d)
        self.assertEqual(rec["failure"], "policy_gap")
        self.assertEqual(rec["evidence"], "档案 §1")

    def test_context_recorded_not_formation(self):
        """v3：字段从 `formation` 改名 `context`，值为 session / review / eval。"""
        d = self._persona()
        rc, _, se = run("feedback_log.py", "--persona-dir", d, "--failure", "in_scope_gap",
                        "--question", "q", "--evidence", "e", "--material-sha", "a",
                        "--context", "session")
        self.assertEqual(rc, 0, se)
        rec = self._last(d)
        self.assertEqual(rec["context"], "session")
        self.assertNotIn("formation", rec)

    def test_incoherent_accepted(self):
        """v3 新增：`incoherent`（模型互相矛盾）属人格缺陷。"""
        d = self._persona()
        rc, so, se = run("feedback_log.py", "--persona-dir", d, "--failure", "incoherent",
                         "--question", "q", "--evidence", "公理集 A2", "--material-sha", "a",
                         "--context", "eval")
        self.assertEqual(rc, 0, se)
        rec = self._last(d)
        self.assertEqual(rec["failure"], "incoherent")
        self.assertIn("人格缺陷", so)

    def test_bogus_context_refused(self):
        d = self._persona()
        rc, _, se = run("feedback_log.py", "--persona-dir", d, "--failure", "in_scope_gap",
                        "--question", "q", "--evidence", "e", "--material-sha", "a",
                        "--context", "bogus")
        self.assertEqual(rc, 1)
        self.assertIn("bogus", se)
        self.assertFalse(os.path.exists(os.path.join(d, "FEEDBACK.jsonl")))

    def test_legacy_formation_alias_accepted(self):
        """向后兼容：`--formation` 是 `--context` 的旧名，接受并提示弃用。"""
        d = self._persona()
        rc, _, se = run("feedback_log.py", "--persona-dir", d, "--failure", "in_scope_gap",
                        "--question", "q", "--evidence", "e", "--material-sha", "a",
                        "--formation", "review")
        self.assertEqual(rc, 0, se)
        self.assertIn("已弃用", se)
        rec = self._last(d)
        self.assertEqual(rec["context"], "review")
        self.assertNotIn("formation", rec)

    def test_ownership_allowlist(self):
        """回归 B5：曾是 3 文件名黑名单，能写进任意目录。"""
        bad = os.path.join(self.tmp, "not-a-persona")
        os.makedirs(bad)
        rc, _, se = run("feedback_log.py", "--persona-dir", bad, "--failure", "in_scope_gap",
                        "--question", "q", "--evidence", "e", "--material-sha", "a")
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(bad, "FEEDBACK.jsonl")))
        # 也不许写进含 MATERIAL.md 的源材料目录（材料归用户管）
        mat = os.path.join(self.tmp, "d-persona")
        write(os.path.join(mat, "SKILL.md"), "---\nname: d-persona\n---\n")
        write(os.path.join(mat, "MATERIAL.md"), "x")
        rc, _, _ = run("feedback_log.py", "--persona-dir", mat, "--failure", "in_scope_gap",
                       "--question", "q", "--evidence", "e", "--material-sha", "a")
        self.assertEqual(rc, 1)


# ------------------------------------------------------------------- calibrate

class TestCalibrate(Base):
    def _persona(self):
        d = os.path.join(self.tmp, "p-persona")
        write(os.path.join(d, "SKILL.md"), "---\nname: p-persona\n---\n# p\n")
        return d

    def test_add_list_revoke(self):
        d = self._persona()
        rc, _, se = run("calibrate.py", "add", "--persona-dir", d,
                        "--trigger", "被问标的", "--action", "拒绝给操作建议",
                        "--source", "FEEDBACK 2026-09-24 in_scope_gap")
        self.assertEqual(rc, 0, se)
        text = read(os.path.join(d, "CALIBRATION.md"))
        self.assertIn("被问标的", text)
        self.assertIn("生效中", text)
        rc, so, _ = run("calibrate.py", "list", "--persona-dir", d)
        self.assertIn("生效中", so)
        rc, _, se = run("calibrate.py", "revoke", "--persona-dir", d, "--index", "1",
                        "--reason", "根因已消失")
        self.assertEqual(rc, 0, se)
        text = read(os.path.join(d, "CALIBRATION.md"))
        self.assertIn("已撤销", text)
        self.assertIn("根因已消失", text)

    def test_source_required(self):
        d = self._persona()
        rc, _, _ = run("calibrate.py", "add", "--persona-dir", d,
                       "--trigger", "t", "--action", "a")
        self.assertEqual(rc, 1)

    def test_limit_ten_rows(self):
        d = self._persona()
        for i in range(10):
            rc, _, se = run("calibrate.py", "add", "--persona-dir", d,
                            "--trigger", "触发%d" % i, "--action", "收窄%d" % i,
                            "--source", "FEEDBACK 2026-09-2%d x" % (i % 10))
            self.assertEqual(rc, 0, se)
        rc, _, se = run("calibrate.py", "add", "--persona-dir", d,
                        "--trigger", "第十一条", "--action", "收窄", "--source", "s")
        self.assertEqual(rc, 1)
        self.assertIn("10", se + "")


# ------------------------------------------------------------------ eval_record

class TestEvalRecord(Base):
    def _f(self):
        return os.path.join(self.tmp, "EVALS.jsonl")

    def _rec(self, **kw):
        rec = {
            "version": 1, "date": "2026-09-22", "artifact_sha256": "aa",
            "models": {"answer": "m-a", "score": "m-b"}, "scorers": 2,
            "questions": [{"id": "q1", "kind": "known", "text": "t", "status": "active"}],
            "axes": dict(DEFAULT_AXES),
            "total": DEFAULT_TOTAL, "grade": "B", "mode": "full",
        }
        rec.update(kw)
        return json.dumps(rec, ensure_ascii=False)

    def _record(self, rec):
        return run("eval_record.py", "record", "--file", self._f(), "--json",
                   json.dumps(rec, ensure_ascii=False) if isinstance(rec, dict) else rec)

    def test_refuses_missing_question_set(self):
        """回归 E4：无题目集的两条记录曾给出「✅ 对比有效 总分 +40」。"""
        f = self._f()
        for total in (40, 80):
            rec = json.loads(self._rec(total=total))
            rec.pop("questions")
            rc, _, se = self._record(rec)
            self.assertNotEqual(rc, 0, "record 应拒绝无题目集")
        self.assertFalse(os.path.exists(f))

    def test_models_must_have_answer_and_score(self):
        """回归 E7：只校验了 score。"""
        rec = json.loads(self._rec())
        rec["models"] = {"score": "only"}
        rc, _, _ = self._record(rec)
        self.assertNotEqual(rc, 0)

    def test_refuses_missing_axes(self):
        """v3：score payload 是四轴——缺 `axes` 即拒绝（旧 `fidelity` 形状例外）。"""
        rec = json.loads(self._rec())
        rec.pop("axes")
        rc, _, se = self._record(rec)
        self.assertNotEqual(rc, 0)
        self.assertIn("axes", se)

    def test_refuses_incomplete_axes(self):
        rec = json.loads(self._rec())
        rec["axes"].pop("溯源")
        rc, _, se = self._record(rec)
        self.assertNotEqual(rc, 0)
        self.assertIn("溯源", se)

    def test_record_accepts_legacy_shape(self):
        """向后兼容：旧 `fidelity` / `scores` 形状仍可写入，但提示弃用。"""
        rec = json.loads(self._rec())
        rec.pop("axes")
        rec.pop("total")
        rec["fidelity"] = {"total": 70, "grade": "B", "scores": {"立场一致性": 20}}
        rc, so, se = self._record(rec)
        self.assertEqual(rc, 0, se)
        self.assertIn("旧格式", so)

    def test_noise_requires_value(self):
        """回归 E5：裸 --noise 曾变成 1，悄悄缩小噪声带。"""
        f = self._f()
        rc, _, _ = run("eval_record.py", "record", "--file", f, "--json", self._rec())
        self.assertEqual(rc, 0)
        rc, so, se = run("eval_record.py", "compare", "--file", f, "--noise")
        self.assertNotEqual(rc, 0, "裸 --noise 应报错")

    def test_survives_non_object_lines(self):
        """回归 E3：EVALS.jsonl 里一行 `123` 曾让 history 崩掉。"""
        f = self._f()
        write(f, "123\n" + self._rec() + "\n")
        rc, so, se = run("eval_record.py", "history", "--file", f)
        self.assertNotIn("Traceback", se)

    def test_string_scorers_does_not_crash(self):
        """回归 E1：`scorers: "2"` 曾 TypeError。"""
        rec = json.loads(self._rec())
        rec["scorers"] = "2"
        rc, so, se = self._record(rec)
        self.assertNotIn("Traceback", se)

    def test_history_prints_four_axes_separately(self):
        """四轴必须分开报；脚本绝不把四个数相加（20+18+12+15=65 ≠ total 82）。"""
        f = self._f()
        run("eval_record.py", "record", "--file", f, "--json", self._rec())
        rc, so, _ = run("eval_record.py", "history", "--file", f)
        for frag in ("生成力/30", "自洽性/25", "辨识度/20", "溯源/25"):
            self.assertIn(frag, so)
        for v in ("20", "18", "12", "15", "82"):
            self.assertIn(v, so)
        self.assertNotIn("65", so)   # 相加的结果绝不能出现

    def test_legacy_record_still_readable(self):
        """向后兼容：旧 `fidelity` / `generativity` 记录 history 不崩。"""
        f = self._f()
        legacy = {"version": 1, "artifact_sha256": "aa",
                  "models": {"answer": "a", "score": "b"}, "scorers": 2,
                  "questions": [{"id": "q1", "status": "active"}],
                  "fidelity": {"total": 70, "grade": "B", "scores": {"立场一致性": 20}},
                  "generativity": {"total": 13, "probes": []}}
        write(f, json.dumps(legacy, ensure_ascii=False) + "\n")
        rc, so, se = run("eval_record.py", "history", "--file", f)
        self.assertEqual(rc, 0, se)
        self.assertNotIn("Traceback", se)
        self.assertIn("70", so)
        self.assertIn("旧格式", so)

    def test_compare_refuses_within_noise(self):
        """噪声带内拒绝给趋势结论（退出码 2）。"""
        f = self._f()
        for v, total in ((1, 80), (2, 84)):
            self._record(json.loads(self._rec(version=v, total=total,
                                              artifact_sha256="a%d" % v)))
        rc, so, se = run("eval_record.py", "compare", "--file", f)
        self.assertEqual(rc, 2, so + se)
        self.assertIn("噪声带", so)

    def test_compare_reports_axes_separately(self):
        """有效对比时四轴各画一行，绝不相加。"""
        f = self._f()
        for v, total in ((1, 60), (2, 90)):
            self._record(json.loads(self._rec(version=v, total=total,
                                              artifact_sha256="a%d" % v)))
        rc, so, se = run("eval_record.py", "compare", "--file", f)
        self.assertEqual(rc, 0, so + se)
        for frag in ("生成力/30", "自洽性/25", "辨识度/20", "溯源/25", "总分/100"):
            self.assertIn(frag, so)


# ---------------------------------------------------------------- fidelity_check

class TestFidelityCheck(Base):
    def test_help(self):
        rc, out, _ = run("fidelity_check.py", "--help")
        self.assertEqual(rc, 0)
        self.assertTrue(out.strip())
        self.assertIn("四轴", out)

    def test_example_persona_passes(self):
        rc, so, _ = run("fidelity_check.py",
                        os.path.join(ROOT, "examples", "skeptic-cfo-persona", "SKILL.md"))
        self.assertEqual(rc, 0, so)

    def test_content_free_stub_fails(self):
        """回归 C1：30 行空壳曾 6/6 PASS。"""
        p = os.path.join(self.tmp, "stub-persona", "SKILL.md")
        write(p, "---\nname: stub-persona\n---\n# stub\n## 角色扮演规则\nSTOP EXIT\n")
        rc, so, _ = run("fidelity_check.py", p)
        self.assertEqual(rc, 1, so)

    def test_roster_fields_axes_required_legacy_warns(self):
        """v3：`axes` 四轴必填；旧 `fidelity` 接受但 WARN；`axes` 缺轴即 FAIL。"""
        sys.path.insert(0, SCRIPTS)
        import fidelity_check as fc
        base = {"name": "p", "persona_type": "real", "source_material": "s",
                "source_material_sha256": "a", "source_material_version": "2",
                "updated": "2026-09-24", "triggers": ["t"], "status": "active"}
        st, detail = fc.check_roster_fields(dict(base, fidelity={"total": 80}), "", {})
        self.assertEqual(st, "warn", detail)
        self.assertIn("已弃用", detail)
        st, detail = fc.check_roster_fields(
            dict(base, axes={"生成力": 20, "自洽性": 18}), "", {})
        self.assertEqual(st, "fail", detail)
        self.assertIn("缺轴", detail)
        st, detail = fc.check_roster_fields(
            dict(base, axes={"生成力": 20, "自洽性": 18, "辨识度": 12, "溯源": 15}), "", {})
        self.assertEqual(st, "pass", detail)

    def test_archetype_without_axioms_fails(self):
        """v3 新增：合成型的公理集必须解析到、且哈希一致。"""
        d = os.path.join(self.tmp, "a-persona")
        write(os.path.join(d, "SKILL.md"),
              "---\nname: a-persona\npersona_type: archetype\n"
              "source_axioms: references/AXIOMS.md\nsource_axioms_sha256: deadbeef\n"
              "axes: {生成力: 10, 自洽性: 10, 辨识度: 10, 溯源: 10, total: 40}\n---\n# a\n")
        rc, so, _ = run("fidelity_check.py", os.path.join(d, "SKILL.md"))
        self.assertEqual(rc, 1)
        self.assertIn("公理集", so)

    def test_archetype_axioms_hash_mismatch_fails(self):
        d = os.path.join(self.tmp, "b-persona")
        write(os.path.join(d, "references", "AXIOMS.md"), "# 公理集\n")
        write(os.path.join(d, "SKILL.md"),
              "---\nname: b-persona\npersona_type: archetype\n"
              "source_axioms: references/AXIOMS.md\nsource_axioms_sha256: deadbeef\n"
              "axes: {生成力: 10, 自洽性: 10, 辨识度: 10, 溯源: 10, total: 40}\n---\n# b\n")
        rc, so, _ = run("fidelity_check.py", os.path.join(d, "SKILL.md"))
        self.assertEqual(rc, 1)
        self.assertIn("哈希不一致", so)


class TestGenericInput(Base):
    """**输入没有格式要求**：任意文件、任意文件名、无 frontmatter 都能铸。

    输入通用原则：`references/design-philosophy.md` §零；可选落盘约定：`references/roster-format.md` §一。
    """

    BARE = ("# 老王谈成本\n\n## 心智模型 / 核心骨架\n\n"
            "### 单位经济学优先\n先算单笔账。\n"
            "### 现金流是唯一真相\n利润可以美化，现金不会。\n")

    def _bare(self, name):
        p = os.path.join(self.tmp, name)
        write(p, self.BARE)
        return p

    def test_bare_text_without_frontmatter_forges(self):
        """裸文本 + 无 frontmatter → 照铸，只告警。"""
        src = self._bare("notes.txt")
        out = os.path.join(self.tmp, "skills", "notes-persona")
        rc, so, se = run("forge_scaffold.py", src, "--out", out, "--type", "real")
        self.assertEqual(rc, 0, se)
        self.assertIn("没有 frontmatter", se)
        text = read(os.path.join(out, "SKILL.md"))
        self.assertIn("### 模型1: 单位经济学优先", text)
        self.assertIn("source_material_sha256:", text)

    def test_slug_from_file_stem_not_parent_dir(self):
        """回归：曾一律取父目录名，任意文件都会被命名成目录名。"""
        src = self._bare("munger-notes.txt")
        out = os.path.join(self.tmp, "skills", "munger-notes-persona")
        rc, _, se = run("forge_scaffold.py", src, "--out", out, "--type", "real")
        self.assertEqual(rc, 0, se)
        fm, _ = parse_fm(os.path.join(out, "SKILL.md"))
        self.assertEqual(fm["name"], "munger-notes-persona")
        # 任意文件：来源记**路径**（否则 roster 之后再也找不到它）
        self.assertTrue(str(fm["source_material"]).endswith("munger-notes.txt"))

    def test_non_ascii_filename_asks_for_slug(self):
        """中文文件名推不出 slug → 明确要求 --slug（只约束人格名，不约束材料格式）。"""
        src = self._bare("我的访谈记录.txt")
        out = os.path.join(self.tmp, "skills", "laowang-persona")
        rc, _, se = run("forge_scaffold.py", src, "--out", out, "--type", "real")
        self.assertEqual(rc, 1)
        self.assertIn("--slug", se)
        rc, _, se = run("forge_scaffold.py", src, "--out", out, "--type", "real",
                        "--slug", "laowang")
        self.assertEqual(rc, 0, se)
        fm, _ = parse_fm(os.path.join(out, "SKILL.md"))
        self.assertEqual(fm["name"], "laowang-persona")          # --slug 决定人格名
        self.assertTrue(str(fm["source_material"]).endswith("我的访谈记录.txt"))

    def test_directory_input(self):
        d = os.path.join(self.tmp, "notes")
        write(os.path.join(d, "散记.md"), self.BARE)
        out = os.path.join(self.tmp, "skills", "notes-persona")
        rc, _, se = run("forge_scaffold.py", d, "--out", out, "--type", "real",
                        "--slug", "notes")
        self.assertEqual(rc, 0, se)
        fm, _ = parse_fm(os.path.join(out, "SKILL.md"))
        self.assertEqual(fm["name"], "notes-persona")
        self.assertTrue(str(fm["source_material"]).endswith("散记.md"))

    def test_zero_file_oral_source(self):
        """**零文件**：材料只在对话里（纯口述）→ 也能铸；漂移报 none，不算缺字段。"""
        out = os.path.join(self.tmp, "skills", "laowang-persona")
        rc, so, se = run("forge_scaffold.py", "--source-desc", "口述 2026-09-24",
                         "--slug", "laowang", "--out", out, "--type", "real")
        self.assertEqual(rc, 0, se)
        text = read(os.path.join(out, "SKILL.md"))
        self.assertIn("source_material: 口述 2026-09-24", text)
        self.assertIn("source_material_sha256: null", text)
        rc, so, _ = run("roster.py", "--skills-dir", os.path.join(self.tmp, "skills"),
                        "--source-dir", os.path.join(self.tmp, "nope"))
        self.assertEqual(rc, 0)
        # `source_material` 在、sha256 可选 → 不报「缺来源字段」
        self.assertNotIn("缺必填字段: source_material", so)
        self.assertIn("漂移检测对该人格不可用", so)   # 如实说检测不了
        self.assertNotIn("建议重铸", so)              # 但绝不谎报 stale

    def test_source_desc_conflicts_with_material(self):
        """材料路径 / --axioms / --source-desc 三选一，不许同时给。"""
        rc, _, se = run("forge_scaffold.py", "x.txt", "--source-desc", "y",
                        "--out", os.path.join(self.tmp, "o-persona"))
        self.assertEqual(rc, 1)
        self.assertIn("只能给一个", se)

    def test_directory_without_ground_truth_is_actionable(self):
        d = os.path.join(self.tmp, "empty")
        os.makedirs(d)
        write(os.path.join(d, "a.txt"), "x")
        rc, _, se = run("forge_scaffold.py", d, "--out",
                        os.path.join(self.tmp, "skills", "e-persona"), "--type", "real")
        self.assertEqual(rc, 1)
        self.assertIn("ground truth", se)

    def test_drift_is_opportunistic_not_required(self):
        """漂移检测是**机会性**的：文件没了 → unknown，**不是 stale**（不谎报「该重铸」）。"""
        src = self._bare("notes.txt")
        out = os.path.join(self.tmp, "skills", "notes-persona")
        rc, _, se = run("forge_scaffold.py", src, "--out", out, "--type", "real")
        self.assertEqual(rc, 0, se)
        skills = os.path.join(self.tmp, "skills")

        rc, so, _ = run("roster.py", "--skills-dir", skills, "--source-dir", self.tmp)
        self.assertEqual(rc, 0)
        self.assertNotIn("建议重铸", so)          # 材料还在 → ok

        os.remove(src)
        rc, so, _ = run("roster.py", "--skills-dir", skills, "--source-dir", self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("无法核对", so)             # 找不到了 → 如实说无法核对
        self.assertNotIn("建议重铸", so)          # 但绝不谎报 stale

    def test_no_hash_records_none_not_stale(self):
        """从没记过哈希（纯粘贴文本）→ 漂移报 none，不是 stale，也不算缺字段。"""
        d = os.path.join(self.tmp, "skills", "pasted-persona")
        write(os.path.join(d, "SKILL.md"),
              "---\nschema_version: 2\nname: pasted-persona\npersona_type: real\n"
              "source_material: 口述 2026-09-24\n"
              "axes: {生成力: 20, 自洽性: 18, 辨识度: 12, 溯源: 15, total: 82}\n"
              "updated: 2026-09-24\ntriggers: [专属词]\nstatus: active\n---\n# p\n")
        rc, so, _ = run("roster.py", "--skills-dir", os.path.join(self.tmp, "skills"),
                        "--source-dir", os.path.join(self.tmp, "nope"))
        self.assertEqual(rc, 0)
        self.assertNotIn("缺必填字段", so)
        self.assertNotIn("建议重铸", so)
        self.assertIn("漂移检测对该人格不可用", so)


if __name__ == "__main__":
    unittest.main(verbosity=2)
