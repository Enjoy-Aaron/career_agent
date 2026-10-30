# -*- coding: utf-8 -*-
"""排程调试脚本：直接调用内部函数，打印候选构建各环节事实。

用法：python scripts/debug_build.py
"""
import math
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.storage import load_json
from core import planner

DATA = os.path.join(BASE_DIR, "data")
jobs_doc = load_json(os.path.join(DATA, "jobs.json"))
activities_doc = load_json(os.path.join(DATA, "activities.json"))
profile = {
    "major": "计算机科学与技术", "semester": 3, "target_family": "backend",
    "weekly_hours": 8, "path": "employment",
    "mastered_skills": ["python", "git", "data_structure"], "pending_skills": [],
}

# 模拟分析（mock 规则提取）
from core.model_adapter import ModelAdapter
adapter = ModelAdapter({"mode": "mock"}, os.path.join(DATA, "skill_taxonomy.json"))
extractions = [adapter.extract_job(j["raw_text"], j["job_id"]) for j in jobs_doc["jobs"]]
aggregate = planner.aggregate_analysis(extractions, jobs_doc)
gap = planner.gap_analysis(profile, aggregate)

activities = activities_doc["activities"]
by_id = {a["activity_id"]: a for a in activities}
gap_ids = ({s["skill_id"] for s in gap["required_gaps"]}
           | {s["skill_id"] for s in gap["bonus_gaps"]})
mastered = set(profile["mastered_skills"])
core_threshold = math.ceil(gap["job_count"] * 0.6)
core_set = {s["skill_id"] for s in gap["required_gaps"]
            if s["required_count"] >= core_threshold}
print("job_count:", gap["job_count"], "core_threshold:", core_threshold)
print("core_set:", sorted(core_set))
print("\n候选筛选：")
target = []
for a in activities:
    reasons = []
    if a["activity_id"] in set():
        reasons.append("done")
    if a.get("relevant_family") not in ("backend", "both"):
        reasons.append("family")
    if not gap_ids.intersection(a["covers_skills"]):
        reasons.append("no-gap")
    if set(a["covers_skills"]).issubset(mastered):
        reasons.append("all-mastered")
    keep = not reasons
    print(f"  {a['activity_id']} {a['name']:<22} keep={keep} {reasons}")
    if keep:
        target.append(a)

target2 = planner._include_prerequisites(target, activities, set(), "backend")
print("\n拉入先修后:", sorted(a["activity_id"] for a in target2))

req_rank = {s["skill_id"]: s["required_count"] for s in gap["required_gaps"]}
bonus_rank = {s["skill_id"]: s["bonus_count"] for s in gap["bonus_gaps"]}
for a in sorted(target2, key=lambda x: planner._topo_level(x, by_id, "backend")):
    lvl = planner._topo_level(a, by_id, "backend")
    cv = sum(req_rank.get(s, 0) for s in a["covers_skills"] if s in core_set)
    tv = (sum(req_rank.get(s, 0) for s in a["covers_skills"] if s not in core_set)
          + sum(bonus_rank.get(s, 0) for s in a["covers_skills"]))
    print(f"  level={lvl} core={cv} tail={tv} {a['activity_id']} {a['name']} prereq={a['prerequisites']} window={a['semester_window']}")
