# -*- coding: utf-8 -*-
"""计划内容检查脚本：按指定路径生成并打印完整计划，便于人工核对。

用法：
  python scripts/inspect_plan.py employment backend
  python scripts/inspect_plan.py postgraduate ai
  python scripts/inspect_plan.py recommendation backend
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
path = sys.argv[1] if len(sys.argv) > 1 else "employment"
family = sys.argv[2] if len(sys.argv) > 2 else "backend"


def call(p, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + p, data=data, headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


call("/api/reset", {})
profile = {
    "major": "计算机科学与技术", "semester": 3, "target_family": family,
    "weekly_hours": 8, "path": path,
    "mastered_skills": ["python", "git", "data_structure"], "pending_skills": [],
}
call("/api/profile", profile)
call("/api/tool/analyze_jobs", {"family": "all"})
r = call("/api/tool/generate_plan", {})
print("生成结果:", r)
plan = call("/api/plan/latest")["plan"]
print("计划:", plan["plan_id"], "| 缺口:", plan["gap_summary"])
for sp in plan["semester_plans"]:
    print(f"--- 第{sp['semester']}学期 预算{sp['budget_hours']} 已排{sp['total_hours']} 余{sp['remaining_budget']}")
    for it in sp["fixed"] + sp["scheduled"]:
        tag = " [固定块]" if it["status"] == "fixed" else ""
        print("   *", it["name"], f"{it['workload_hours']}h", tag)
for b in plan["summer_blocks"]:
    print(f"暑期块(第{b['after_semester']}学期后): {b['name']} {b['workload_hours']}h")
print("未安排:")
for u in plan["unallocated"]:
    print("  -", u["name"], "|", u["reason"])
print("校验:", plan["validation"]["passed"])
