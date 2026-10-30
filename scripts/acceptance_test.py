# -*- coding: utf-8 -*-
"""端到端验收脚本：覆盖作业框架的 6 个验收场景。

运行前提：已启动服务（python app.py --no-browser）。
运行方式：python scripts/acceptance_test.py
输入：内置 8 条真实招聘样本 + 测试画像；输出：每步 PASS/FAIL 与关键事实。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0


def call(path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name} {detail}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


# 干净起点
call("/api/reset", {})
status = call("/api/model_status")["status"]
check("场景0 默认模拟模式", status["mode"] == "mock", str(status))

# 画像：大二第3学期，后端岗，每周8小时，就业路径
profile = {
    "major": "计算机科学与技术", "semester": 3, "target_family": "backend",
    "weekly_hours": 8, "path": "employment",
    "mastered_skills": ["python", "git", "data_structure"],
    "pending_skills": [],
}
check("保存画像", call("/api/profile", profile)["ok"])

# ---------- 场景1：分析真实招聘 ----------
r = call("/api/tool/analyze_jobs", {"family": "all"})
check("场景1 分析8条招聘", r["ok"] and r["analyzed_jobs"] == 8, f"analyzed={r.get('analyzed_jobs')}")

agg = call("/api/tool/get_aggregate", {})["aggregate"]
bk = next(f for f in agg["families"] if f["family"] == "backend")
ai = next(f for f in agg["families"] if f["family"] == "ai")
bk_ids = {s["skill_id"]: s for s in bk["skills"]}
print("\n后端族高频技能（硬性/加分/频率）：")
for s in bk["skills"][:8]:
    print(f"  {s['name']:<16} 硬{s['required_count']} 加{s['bonus_count']} 频率{s['mention_freq']}")
check("场景1 硬性与加分分开统计", all(s["required_count"] + s["bonus_count"] > 0 for s in bk["skills"]))
check("场景1 Java 为后端高频硬性要求", bk_ids["java"]["required_count"] >= 4,
      f"java required={bk_ids['java']['required_count']}")
check("场景1 证据保留来源链接", all(e["source_url"].startswith("http") for e in bk_ids["mysql"]["evidence"]))
# 学历：AI 族存在硕士门槛岗位
ai_degrees = set()
for s in ai["skills"]:
    for e in s["evidence"]:
        if "爱迪特" in e["company"]:
            ai_degrees.add(e["company"])
check("场景1 AI族含硕士门槛岗位证据", bool(ai_degrees), str(ai_degrees))

# ---------- 差距 ----------
gap = call("/api/tool/get_gap", {})["gap"]
check("差距分析输出硬性缺口", len(gap["required_gaps"]) > 0,
      f"硬性缺口{len(gap['required_gaps'])}个，加分缺口{len(gap['bonus_gaps'])}个")
check("后端族无硕士门槛提示", all("硕士" not in n["message"] for n in gap["degree_notes"]))

# ---------- 场景2：生成成长路线 ----------
r = call("/api/tool/generate_plan", {})
check("场景2 计划生成并通过校验", r["ok"] and r["version"] == 1, str(r.get("plan_id")))
plan = call("/api/plan/latest", )["plan"]
semesters = [sp["semester"] for sp in plan["semester_plans"]]
check("场景2 覆盖第3-8剩余学期", semesters == list(range(3, 9)), str(semesters))
check("场景2 各学期不超预算", all(sp["total_hours"] <= sp["budget_hours"] for sp in plan["semester_plans"]))
check("场景2 含未来四周任务", len(plan["near_term"]["weeks"]) == 4)
check("场景2 周任务不超每周8小时", all(w["week_hours"] <= 8 for w in plan["near_term"]["weeks"]))
check("场景2 任务含交付物与验收", all(
    t["deliverable"] and t["acceptance"] for w in plan["near_term"]["weeks"] for t in w["tasks"]))
print("\n首学期四周工时：", [w["week_hours"] for w in plan["near_term"]["weeks"]])

# ---------- 记录一个完成 ----------
first_aid = plan["semester_plans"][0]["scheduled"][0]["activity_id"]
check("记录完成", call("/api/tool/update_completion", {"activity_id": first_aid})["ok"], first_aid)

# ---------- 场景3：8小时改4小时 ----------
r = call("/api/tool/adjust_conditions", {"weekly_hours": 4})
check("场景3 调整成功并生成V2", r["ok"] and r["version"] == 2)
plan4 = call("/api/plan/latest")["plan"]
check("场景3 学期预算降为64h", all(abs(sp["budget_hours"] - 64) < 0.01 for sp in plan4["semester_plans"]))
check("场景3 工时不超新预算", all(sp["total_hours"] <= 64 for sp in plan4["semester_plans"]))
check("场景3 出现延期或未安排项",
      len(r["diff"]["deferred"]) + len(plan4["unallocated"]) > 0,
      f"延期{len(r['diff']['deferred'])} 未安排{len(plan4['unallocated'])}")
check("场景3 已完成活动保留", first_aid not in [x["activity_id"] for x in plan4["unallocated"]])

# ---------- 场景4：切换目标岗位 ----------
r = call("/api/tool/adjust_conditions", {"target_family": "ai"})
check("场景4 切换成功并生成V3", r["ok"] and r["version"] == 3)
check("场景4 差异说明含岗位切换", "切换" in r["diff"]["impact"], r["diff"]["impact"])
plan_ai = call("/api/plan/latest")["plan"]
check("场景4 已完成成果保留", first_aid in call("/api/state")["completions"])
gap_ai = call("/api/tool/get_gap", {})["gap"]
check("场景4 按AI岗重新分析缺口", gap_ai["family"] == "ai")
check("场景4 AI族识别硕士门槛岗位",
      any(n["level"] == "master_or_above" and n["job_ids"] == ["J008"] for n in gap_ai["degree_notes"]),
      str(gap_ai["degree_notes"]))

# ---------- 场景5：重启恢复（持久化文件） ----------
state = call("/api/state")
check("场景5 状态可读取", state["plan_versions"] == 3 and state["profile"]["target_family"] == "ai")

# ---------- 场景6：异常与边界 ----------
call("/api/reset", {})
r = call("/api/tool/get_gap", {})
check("场景6 缺资料时友好报错", not r["ok"] and "先" in r["message"], r["message"])
r = call("/api/tool/analyze_jobs", {"family": "bad_value"})
check("场景6 非法枚举被拦截", not r["ok"])
# 白名单外工具（run_tool 捕获后返回 200 且 ok=false）
body = call("/api/tool/evil_tool", {})
check("场景6 白名单外工具被拒", not body["ok"] and "白名单" in body["error"][0], str(body))

# 重新走一遍完整流程并导出报告
call("/api/profile", profile)
call("/api/tool/analyze_jobs", {"family": "all"})
call("/api/tool/generate_plan", {})
rep = call("/api/tool/export_report", {})
check("报告导出", rep["ok"] and rep["filename"].endswith(".md"))
check("报告含来源链接", "http" in rep["report_markdown"])

print(f"\n========== 验收结果：{PASS} PASS / {FAIL} FAIL ==========")
