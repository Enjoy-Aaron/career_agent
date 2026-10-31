# -*- coding: utf-8 -*-
"""planner.py 纯函数单元测试（标准库 unittest，零第三方依赖）。

覆盖：招聘聚合、能力差距、路径建议等级、学期排程（先修/窗口/预算/去重/
recurring 拆分）、计划校验、版本差异。与端到端 acceptance_test.py 互补：
端到端验证“整条链路可用”，本测试验证“规则引擎每个函数在边界下正确”。

运行：python scripts/test_planner.py
"""
import json
import os
import sys
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core import planner  # noqa: E402


def _load(name):
    with open(os.path.join(BASE, "data", name), encoding="utf-8") as f:
        return json.load(f)


JOBS = _load("jobs.json")
ACTIVITIES = _load("activities.json")
ACT_BY_ID = {a["activity_id"]: a for a in ACTIVITIES["activities"]}


def _make_extraction(job_id, skills, degree="bachelor_or_above"):
    """构造一条招聘提取结果（字段与 model_adapter 输出一致）。"""
    return {
        "job_id": job_id,
        "skills": skills,
        "degree": {"level": degree, "quote": "本科及以上"},
        "experience": {"type": "campus", "quote": "应届"},
    }


def _skill(sid, req="required"):
    name = {"java": "Java", "mysql": "MySQL", "git": "Git",
            "english": "英语"}.get(sid, sid)
    return {"skill_id": sid, "name": name, "category": "cs_foundation",
            "requirement": req, "quotes": ["原文证据"]}


class TestAggregate(unittest.TestCase):
    def test_去重招聘数与频次(self):
        """同一岗位族只计一次；频次=去重招聘数/该族招聘数。"""
        jobs_meta = {"jobs": [
            {"job_id": "J1", "family": "backend", "company": "A", "source_url": ""},
            {"job_id": "J2", "family": "backend", "company": "B", "source_url": ""},
            {"job_id": "J3", "family": "ai", "company": "C", "source_url": ""},
        ]}
        exts = [
            _make_extraction("J1", [_skill("java"), _skill("mysql")]),
            _make_extraction("J2", [_skill("java")]),
            _make_extraction("J3", [_skill("java", "bonus")]),
        ]
        agg = planner.aggregate_analysis(exts, jobs_meta)
        backend = next(f for f in agg["families"] if f["family"] == "backend")
        self.assertEqual(backend["job_count"], 2)
        java = next(s for s in backend["skills"] if s["skill_id"] == "java")
        self.assertEqual(java["required_count"], 2)   # J1、J2 都硬性要求 java
        self.assertEqual(java["required_freq"], 1.0)

    def test_同族同一技能去重(self):
        """同一条招聘内重复命中同一技能只计一次。"""
        jobs_meta = {"jobs": [{"job_id": "J1", "family": "backend", "company": "A", "source_url": ""}]}
        exts = [_make_extraction("J1", [_skill("java"), _skill("java", "bonus")])]
        agg = planner.aggregate_analysis(exts, jobs_meta)
        backend = agg["families"][0]
        java = next(s for s in backend["skills"] if s["skill_id"] == "java")
        # 硬性优先：同技能 required 覆盖 bonus，只计一次
        self.assertEqual(java["required_count"], 1)
        self.assertEqual(java["bonus_count"], 0)


class TestGap(unittest.TestCase):
    def _agg(self):
        jobs_meta = {"jobs": [{"job_id": "J1", "family": "backend", "company": "A", "source_url": ""}]}
        return planner.aggregate_analysis(
            [_make_extraction("J1", [_skill("java"), _skill("mysql")])], jobs_meta)

    def test_硬性与加分缺口分离(self):
        gap = planner.gap_analysis(
            {"target_family": "backend", "mastered_skills": [], "pending_skills": []},
            self._agg())
        req_ids = {s["skill_id"] for s in gap["required_gaps"]}
        self.assertEqual(req_ids, {"java", "mysql"})
        self.assertEqual(gap["bonus_gaps"], [])

    def test_已掌握进入mastered不在缺口(self):
        gap = planner.gap_analysis(
            {"target_family": "backend", "mastered_skills": ["java"], "pending_skills": []},
            self._agg())
        self.assertIn("java", gap["mastered_in_target"])
        self.assertEqual({s["skill_id"] for s in gap["required_gaps"]}, {"mysql"})

    def test_无目标族返回空(self):
        gap = planner.gap_analysis(
            {"target_family": "frontend", "mastered_skills": [], "pending_skills": []},
            self._agg())
        self.assertEqual(gap["job_count"], 0)
        self.assertEqual(gap["required_gaps"], [])


class TestPathAdvice(unittest.TestCase):
    def _fam(self, job_count, master_jobs):
        return {"family": "ai", "job_count": job_count, "master_degree_jobs": master_jobs}

    def test_硕士占比高(self):
        pa = planner._path_advice(self._fam(4, ["J1", "J2", "J3"]), ["J1", "J2", "J3"], "employment")
        self.assertEqual(pa["level"], "master_heavy")
        # 当前路径为就业时，应给出当前路径的建议提示
        self.assertIsNotNone(pa["current_hint"])

    def test_就业友好(self):
        pa = planner._path_advice(self._fam(4, []), [], "employment")
        self.assertEqual(pa["level"], "employment_friendly")

    def test_混合(self):
        pa = planner._path_advice(self._fam(4, ["J1"]), ["J1"], "postgraduate")
        self.assertEqual(pa["level"], "master_mixed")


class TestBuildPlan(unittest.TestCase):
    def _gap(self, required=None, bonus=None, job_count=8):
        return {
            "job_count": job_count,
            "required_gaps": required or [],
            "bonus_gaps": bonus or [],
            "mastered_in_target": [],
            "pending": [],
        }

    def _profile(self, **kw):
        p = {"major": "计算机", "semester": 3, "target_family": "backend",
             "weekly_hours": 8, "path": "employment",
             "mastered_skills": ["python"], "pending_skills": []}
        p.update(kw)
        return p

    def test_排程不超预算(self):
        gap = self._gap(required=[
            {"skill_id": "java", "name": "Java", "category": "cs_foundation", "required_count": 5},
            {"skill_id": "mysql", "name": "MySQL", "category": "data_storage", "required_count": 4},
        ])
        plan = planner.build_plan(self._profile(), gap, ACTIVITIES, [], 1)
        self.assertTrue(plan["validation"]["passed"])
        for sp in plan["semester_plans"]:
            self.assertLessEqual(sp["total_hours"], sp["budget_hours"] + 0.01)

    def test_recurring跨学期拆分(self):
        # 蓝桥杯 A04(recurring)、英语 A13(recurring) 应均摊到多个学期
        gap = self._gap(required=[
            {"skill_id": "data_structure", "name": "数据结构", "category": "cs_foundation", "required_count": 5},
            {"skill_id": "english", "name": "英语", "category": "soft_skill", "required_count": 3},
        ])
        plan = planner.build_plan(self._profile(), gap, ACTIVITIES, [], 1)
        recurring_items = [i for sp in plan["semester_plans"] for i in sp["scheduled"]
                           if i["status"] == "recurring"]
        self.assertTrue(recurring_items, "应存在 recurring 拆分项")
        # 同一 recurring 活动应出现在多个学期
        sems = {}
        for sp in plan["semester_plans"]:
            for i in sp["scheduled"]:
                if i["status"] == "recurring":
                    sems.setdefault(i["activity_id"], []).append(sp["semester"])
        self.assertTrue(any(len(v) > 1 for v in sems.values()),
                        "recurring 活动应跨多个学期均摊")

    def test_考研路径产生固定块(self):
        gap = self._gap(required=[
            {"skill_id": "java", "name": "Java", "category": "cs_foundation", "required_count": 5},
        ])
        plan = planner.build_plan(self._profile(path="postgraduate"), gap, ACTIVITIES, [], 1)
        fixed = [i for sp in plan["semester_plans"] for i in sp["fixed"]]
        self.assertTrue(any(i["activity_id"] == "A23" for i in fixed),
                        "考研路径应产生 A23 固定复习块")

    def test_已完成活动不再安排且技能可迁移(self):
        # 已完成 A03(MySQL)，其覆盖技能 mysql 应视为可迁移，不再重复安排 A03
        gap = self._gap(required=[
            {"skill_id": "mysql", "name": "MySQL", "category": "data_storage", "required_count": 5},
            {"skill_id": "java", "name": "Java", "category": "cs_foundation", "required_count": 5},
        ])
        plan = planner.build_plan(self._profile(), gap, ACTIVITIES, ["A03"], 1)
        ids = [i["activity_id"] for sp in plan["semester_plans"]
               for i in sp["scheduled"] + sp["fixed"]]
        self.assertNotIn("A03", ids, "已完成活动不应重复安排")


class TestValidatePlan(unittest.TestCase):
    def test_通过校验(self):
        gap = {"job_count": 8, "required_gaps": [
            {"skill_id": "mysql", "name": "MySQL", "category": "data_storage", "required_count": 5},
        ], "bonus_gaps": []}
        profile = {"semester": 3, "target_family": "backend", "weekly_hours": 8,
                   "path": "employment", "mastered_skills": ["python"]}
        plan = planner.build_plan(profile, gap, ACTIVITIES, [], 1)
        self.assertTrue(plan["validation"]["passed"])

    def test_窗口越界被检出(self):
        # 构造一个手动篡改窗口的计划，校验应失败
        gap = {"job_count": 8, "required_gaps": [
            {"skill_id": "mysql", "name": "MySQL", "category": "data_storage", "required_count": 5},
        ], "bonus_gaps": []}
        profile = {"semester": 3, "target_family": "backend", "weekly_hours": 8,
                   "path": "employment", "mastered_skills": ["python"]}
        plan = planner.build_plan(profile, gap, ACTIVITIES, [], 1)
        # 强制把某活动塞进不在窗口的学期（第 8 学期安排窗口[2,3]的 A01）
        plan["semester_plans"][-1]["scheduled"].append({
            "activity_id": "A01", "name": "x", "type": "self_study",
            "workload_hours": 10, "covers_skills": ["git"], "deliverable": "",
            "acceptance": "", "status": "scheduled"})
        v = planner.validate_plan(plan, profile, ACT_BY_ID, [])
        self.assertFalse(v["passed"], "窗口越界应导致校验失败")


class TestDiffPlans(unittest.TestCase):
    def _plan(self, sems):
        return {"semester_plans": [
            {"semester": s, "scheduled": [
                {"activity_id": aid, "status": "scheduled", "name": aid,
                 "type": "self_study", "workload_hours": 10,
                 "covers_skills": [], "deliverable": "", "acceptance": ""}],
             "fixed": [], "budget_hours": 100, "total_hours": 10,
             "remaining_budget": 90}
            for s, aid in sems],
            "summer_blocks": [],
            "profile_snapshot": {"target_family": "backend", "weekly_hours": 8, "path": "employment"}}

    def test_新增保留延期移除(self):
        old = self._plan([(3, "A01"), (4, "A02")])
        new = self._plan([(3, "A01"), (5, "A02"), (4, "A03")])
        d = planner.diff_plans(old, new)
        self.assertEqual([x["activity_id"] for x in d["kept"]], ["A01"])
        self.assertEqual([x["activity_id"] for x in d["deferred"]], ["A02"])
        self.assertEqual([x["activity_id"] for x in d["added"]], ["A03"])
        self.assertEqual(d["removed"], [])

    def test_首次生成无历史(self):
        d = planner.diff_plans(None, self._plan([(3, "A01")]))
        self.assertIn("首次生成", d["impact"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
