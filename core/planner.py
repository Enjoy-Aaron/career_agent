# -*- coding: utf-8 -*-
"""规划规则引擎（可验证的确定性计算，模型不参与这些计算）。

职责：
1. 招聘要求聚合：按“去重招聘数”统计技能频次，必须/加分分开，频率只作
   优先级参考、不等于硬门槛；
2. 学生画像与能力差距：区分已掌握、待评估、硬性缺口与加分缺口；
3. 学期排程：先修拓扑 + 每周工时预算 + 学期窗口，实习按暑期块独立安排；
4. 计划校验：预算、先修、窗口、去重逐项检查，不通过的计划不可采纳；
5. 版本差异：新增/保留/延期/移除，已完成成果与可迁移能力不丢失。
"""
import math
from datetime import datetime

TEACHING_WEEKS = 16  # 每学期有效课外周数
NEAR_TERM_WEEKS = 4


# ============================================================
# 1. 招聘要求聚合
# ============================================================
def aggregate_analysis(extractions: list[dict], jobs_meta: dict) -> dict:
    """按岗位族聚合单条提取结果，按去重招聘数统计。"""
    jobs_by_id = {j["job_id"]: j for j in jobs_meta["jobs"]}
    families: dict[str, dict] = {}

    for ext in extractions:
        job = jobs_by_id.get(ext["job_id"])
        if not job:
            continue
        fam = families.setdefault(job["family"], {
            "family": job["family"], "job_ids": [], "job_count": 0, "skills": {},
            "master_degree_jobs": [],
        })
        if ext["job_id"] in fam["job_ids"]:
            continue  # 同一招聘只计一次（转载/重复岗位去重）
        fam["job_ids"].append(ext["job_id"])
        fam["job_count"] += 1
        if ext.get("degree", {}).get("level") == "master_or_above":
            fam["master_degree_jobs"].append(ext["job_id"])

        seen_in_job = set()
        for sk in ext["skills"]:
            sid = sk["skill_id"]
            if sid in seen_in_job:
                continue
            seen_in_job.add(sid)
            entry = fam["skills"].setdefault(sid, {
                "skill_id": sid, "name": sk["name"], "category": sk["category"],
                "required_count": 0, "bonus_count": 0, "evidence": [],
            })
            if sk["requirement"] == "required":
                entry["required_count"] += 1
            else:
                entry["bonus_count"] += 1
            entry["evidence"].append({
                "job_id": ext["job_id"], "company": job["company"],
                "requirement": sk["requirement"], "quotes": sk["quotes"],
                "source_url": job["source_url"],
            })

    result = {"families": [], "generated_at": _now()}
    for fam in families.values():
        total = fam["job_count"]
        skills = list(fam["skills"].values())
        for s in skills:
            s["required_freq"] = round(s["required_count"] / total, 4)
            s["bonus_freq"] = round(s["bonus_count"] / total, 4)
            # 出现频次（任一要求）仅用于优先级参考，不代表硬门槛
            s["mention_freq"] = round((s["required_count"] + s["bonus_count"]) / total, 4)
        # 硬性频次优先，再按提及频次
        skills.sort(key=lambda s: (-s["required_count"], -s["mention_freq"], s["skill_id"]))
        fam["skills"] = skills
        result["families"].append(fam)
    return result


# ============================================================
# 2. 学生画像与能力差距
# ============================================================
def gap_analysis(profile: dict, aggregate: dict) -> dict:
    fam = next((f for f in aggregate["families"] if f["family"] == profile["target_family"]), None)
    if not fam:
        return {"family": profile["target_family"], "job_count": 0,
                "required_gaps": [], "bonus_gaps": [],
                "mastered_in_target": [], "pending": [], "degree_notes": []}

    mastered = set(profile.get("mastered_skills", []))
    pending = set(profile.get("pending_skills", []))
    required_gaps, bonus_gaps, mastered_in_target = [], [], []

    for s in fam["skills"]:
        sid = s["skill_id"]
        if sid in mastered:
            mastered_in_target.append(sid)
        elif s["required_count"] > 0:
            required_gaps.append(s)
        else:
            bonus_gaps.append(s)

    # 学历提示：目标岗位族中存在要求硕士的岗位
    degree_notes = []
    master_jobs = fam.get("master_degree_jobs", [])
    if master_jobs:
        degree_notes.append({
            "level": "master_or_above",
            "message": f"该方向有 {len(master_jobs)} 条岗位要求硕士及以上，本科可投递本科门槛岗位，或通过考研拓宽选择",
            "job_ids": master_jobs,
        })
    # 路径决策建议：硕士门槛岗位占比高时，给出分路径的取舍建议
    path_advice = _path_advice(fam, master_jobs, profile.get("path"))
    return {
        "family": fam["family"],
        "job_count": fam["job_count"],
        "required_gaps": required_gaps,
        "bonus_gaps": bonus_gaps,
        "mastered_in_target": mastered_in_target,
        "pending": sorted(pending),
        "degree_notes": degree_notes,
        "path_advice": path_advice,
    }


def _path_advice(fam: dict, master_jobs: list, current_path: str | None) -> dict:
    """根据硕士门槛岗位占比，输出就业/考研/保研三条路径的时间分配建议。

    这是对"就业、考研等不同路径会怎样改变我的时间分配"这一职业规划思考的
    确定性回答：硕士门槛岗位越多，考研/保研的权重越高，纯就业路径越受限。
    """
    job_count = fam["job_count"] or 1
    master_ratio = len(master_jobs) / job_count
    if master_ratio >= 0.5:
        level = "master_heavy"
        summary = (
            f"该岗位族 {len(master_jobs)}/{job_count} 的招聘要求硕士及以上学历，"
            "学历门槛较高。本科直接就业的选择面会明显收窄，建议优先评估读研路径。"
        )
        suggestions = [
            {"path": "postgraduate", "label": "考研",
             "advice": "若目标院校可行，考研能显著拓宽该方向的岗位选择；需在第 5-6 学期启动系统复习，占用大量课外时间，技术项目相应后置或压缩。"},
            {"path": "recommendation", "label": "保研",
             "advice": "若绩点与科研/竞赛条件达标，保研是时间成本最低的读研路径；需尽早锁定导师课题，科研背景提升优先级高于求职类项目。"},
            {"path": "employment", "label": "直接就业",
             "advice": "可投递的本科门槛岗位减少，需集中精力把核心硬性技术能力做到突出，并锁定不限学历的岗位；风险与竞争压力更高。"},
        ]
    elif master_ratio >= 0.25:
        level = "master_mixed"
        summary = (
            f"该岗位族 {len(master_jobs)}/{job_count} 的招聘要求硕士及以上，"
            "存在学历门槛岗位但本科岗位仍占多数，读研与就业两条路都走得通。"
        )
        suggestions = [
            {"path": "employment", "label": "直接就业",
             "advice": "本科岗位充足，把核心硬性技术能力与 1-2 段实习做扎实即可，时间可充分投入求职准备。"},
            {"path": "postgraduate", "label": "考研",
             "advice": "考研可进一步拓宽选择面，但会挤压第 6-7 学期的项目与实习时间，需权衡目标院校的性价比。"},
            {"path": "recommendation", "label": "保研",
             "advice": "条件达标则优先保研，几乎不影响技术积累节奏，是性价比最高的深造路径。"},
        ]
    else:
        level = "employment_friendly"
        summary = (
            f"该岗位族仅 {len(master_jobs)}/{job_count} 的招聘要求硕士及以上，"
            "本科即可覆盖绝大多数岗位，就业友好。"
        )
        suggestions = [
            {"path": "employment", "label": "直接就业",
             "advice": "学历不是主要门槛，重点补齐核心硬性技术与实习经历，时间分配以求职与项目为主。"},
            {"path": "postgraduate", "label": "考研",
             "advice": "若非出于学术兴趣或目标企业硬性要求，考研的边际收益有限，需谨慎评估机会成本。"},
            {"path": "recommendation", "label": "保研",
             "advice": "若追求深造且条件达标可考虑，但不会带来明显的就业选择增量。"},
        ]
    current = next((s for s in suggestions if s["path"] == current_path), None)
    return {
        "level": level,
        "master_ratio": round(master_ratio, 2),
        "summary": summary,
        "suggestions": suggestions,
        "current_path": current_path,
        "current_hint": current["advice"] if current else None,
    }


# ============================================================
# 3. 学期排程
# ============================================================
def build_plan(profile: dict, gap: dict, activities_doc: dict,
               completed_activity_ids: list[str], plan_version: int) -> dict:
    activities = activities_doc["activities"]
    act_by_id = {a["activity_id"]: a for a in activities}
    current = profile["semester"]
    weekly = float(profile["weekly_hours"])
    semester_budget = weekly * TEACHING_WEEKS

    target_family = profile["target_family"]
    gap_ids = {s["skill_id"] for s in gap["required_gaps"]} | {s["skill_id"] for s in gap["bonus_gaps"]}
    mastered = set(profile.get("mastered_skills", []))
    done_acts = set(completed_activity_ids)
    # 已完成活动覆盖的技能并入可迁移能力
    for aid in done_acts:
        if aid in act_by_id:
            mastered.update(act_by_id[aid]["covers_skills"])

    # 核心硬性缺口：硬性出现次数达到“60% 招聘数向上取整”的技能，
    # 只在少数招聘中出现的长尾技能不进入核心
    core_threshold = math.ceil(gap["job_count"] * 0.6)
    core_skill_set = {s["skill_id"] for s in gap["required_gaps"]
                      if s["required_count"] >= core_threshold}

    def family_ok(a):
        return a.get("relevant_family") in (target_family, "both")

    # 目标活动：本族/both、未完成、覆盖缺口、且仍含未掌握技能
    target_acts = []
    for a in activities:
        if a["activity_id"] in done_acts or not family_ok(a):
            continue
        # 路径专属活动：A22 仅保研路径，考研复习块仅考研路径
        if a["activity_id"] == "A22" and profile["path"] != "recommendation":
            continue
        if a["type"] == "exam_prep" and profile["path"] != "postgraduate":
            continue
        if not gap_ids.intersection(a["covers_skills"]):
            continue
        if set(a["covers_skills"]).issubset(mastered):
            continue
        target_acts.append(a)
    # 递归拉入本族/both 先修活动
    target_acts = _include_prerequisites(target_acts, activities, done_acts, target_family)

    req_rank = {s["skill_id"]: s["required_count"] for s in gap["required_gaps"]}
    bonus_rank = {s["skill_id"]: s["bonus_count"] for s in gap["bonus_gaps"]}
    # 技能类别（用于把通用能力与硬性技术分开）
    cat_map = {s["skill_id"]: s["category"] for s in gap["required_gaps"]}
    cat_map.update({s["skill_id"]: s["category"] for s in gap["bonus_gaps"]})

    def tech_core(a):
        # 核心硬性技术技能（排除通用能力）：岗位真正的技术门槛
        return sum(req_rank.get(sid, 0) for sid in a["covers_skills"]
                   if sid in core_skill_set and cat_map.get(sid) != "soft_skill")

    def soft_core(a):
        return sum(req_rank.get(sid, 0) for sid in a["covers_skills"]
                   if sid in core_skill_set and cat_map.get(sid) == "soft_skill")

    def tail_value(a):
        return (sum(req_rank.get(sid, 0) for sid in a["covers_skills"] if sid not in core_skill_set)
                + sum(bonus_rank.get(sid, 0) for sid in a["covers_skills"]))

    def priority(a):
        # 技术核心优先；同价值按先修层级，再看通用能力与长尾
        return (-tech_core(a),
                _topo_level(a, act_by_id, target_family, mastered),
                -soft_core(a), -tail_value(a), a["workload_hours"])

    ordered = sorted(target_acts, key=priority)

    # 固定块（考研/保研）
    fixed_by_semester: dict[int, list[dict]] = {}
    if profile["path"] == "postgraduate":
        exam = act_by_id.get("A23")
        if exam and current <= 7:
            half = round(exam["workload_hours"] / 2)
            for sem in (6, 7):
                if sem >= current:
                    fixed_by_semester.setdefault(sem, []).append(
                        _scheduled(exam, min(half, semester_budget), "fixed"))
    elif profile["path"] == "recommendation":
        bg = act_by_id.get("A22")
        if bg and current <= 6:
            fixed_by_semester.setdefault(max(current, 3), []).append(
                _scheduled(bg, bg["workload_hours"], "fixed"))

    # 按学期贪心装填
    semester_plans = []
    scheduled_set: set[str] = set()
    skill_available = set(mastered)
    # 持续性任务（recurring）：把总工时均摊到窗口内每个学期，逐学期投入
    recurring_alloc = _plan_recurring(ordered, done_acts, current)

    for sem in range(current, 9):
        fixed = fixed_by_semester.get(sem, [])
        fixed_hours = sum(x["workload_hours"] for x in fixed)
        remaining = semester_budget - fixed_hours
        scheduled = []
        # 先放入持续性任务的当学期份额
        for alloc in recurring_alloc:
            if alloc["activity_id"] in scheduled_set or alloc["activity_id"] in done_acts:
                continue
            share = alloc["per_semester"]
            if share <= remaining:
                a = act_by_id[alloc["activity_id"]]
                scheduled.append(_scheduled(a, share, "recurring"))
                remaining -= share
                scheduled_set.add(alloc["activity_id"])
        for a in ordered:
            aid = a["activity_id"]
            if aid in scheduled_set or aid in done_acts:
                continue
            lo, hi = a["semester_window"]
            if not (lo <= sem <= hi):
                continue
            if a["type"] == "internship" or a["type"] == "exam_prep":
                continue  # 实习走暑期块；考研固定块已处理
            if a.get("recurring"):
                continue  # 持续性任务已单独处理
            if not set(a["prerequisites"]).issubset(skill_available):
                continue
            if a["workload_hours"] <= remaining:
                scheduled.append(_scheduled(a, a["workload_hours"], "scheduled"))
                remaining -= a["workload_hours"]
                scheduled_set.add(aid)
        total = fixed_hours + sum(x["workload_hours"] for x in scheduled)
        semester_plans.append({
            "semester": sem,
            "budget_hours": round(semester_budget, 1),
            "fixed": fixed,
            "scheduled": scheduled,
            "total_hours": round(total, 1),
            "remaining_budget": round(remaining, 1),
        })
        for x in scheduled + fixed:
            skill_available.update(act_by_id[x["activity_id"]]["covers_skills"])

    # 暑期实习块：先修满足后安排到最早暑期
    summer_blocks = []
    for a in ordered:
        if a["type"] != "internship":
            continue
        lo, hi = a["semester_window"]
        for sem in range(max(current, lo), min(hi, 8) + 1):
            prereq_ready = set(a["prerequisites"]).issubset(skill_available) or _prereq_done(a, scheduled_set, done_acts, act_by_id)
            if prereq_ready:
                summer_blocks.append({
                    "after_semester": sem,
                    "activity_id": a["activity_id"],
                    "name": a["name"],
                    "workload_hours": a["workload_hours"],
                    "deliverable": a["deliverable"],
                    "acceptance": a["acceptance"],
                })
                scheduled_set.add(a["activity_id"])
                break

    # 未安排项与处理选项（已作为固定块/暑期块安排的活动不再列入）
    fixed_ids = {item["activity_id"] for items in fixed_by_semester.values() for item in items}
    unallocated = []
    for a in ordered:
        aid = a["activity_id"]
        if aid in fixed_ids or aid in scheduled_set or aid in done_acts:
            continue
        unallocated.append({
            "activity_id": aid,
            "name": a["name"],
            "reason": _reason_unallocated(a, semester_budget),
            "options": ["减少活动范围（优先保硬性缺口）", "延期到后续学期/下个暑期", "增加每周可投入时间"],
        })

    # 固定块工时说明：记录计划工时与预算约束下实际可安排工时
    fixed_block_notes = []
    for aid in sorted(fixed_ids):
        a = act_by_id[aid]
        actual = sum(item["workload_hours"] for items in fixed_by_semester.values()
                     for item in items if item["activity_id"] == aid)
        note = {
            "activity_id": aid, "name": a["name"],
            "planned_hours": a["workload_hours"],
            "scheduled_hours": round(actual, 1),
        }
        if actual < a["workload_hours"]:
            note["shortfall_hours"] = round(a["workload_hours"] - actual, 1)
            note["note"] = (f"当前每周 {profile['weekly_hours']} 小时预算下，"
                            f"学期内最多安排 {round(actual, 1)} 小时，"
                            f"缺口 {round(a['workload_hours'] - actual, 1)} 小时，"
                            "建议增加每周投入或利用假期补量。")
        fixed_block_notes.append(note)

    plan = {
        "plan_id": f"PLAN-V{plan_version}",
        "version": plan_version,
        "created_at": _now(),
        "profile_snapshot": dict(profile),
        "semester_plans": semester_plans,
        "summer_blocks": summer_blocks,
        "near_term": _near_term(profile, semester_plans, act_by_id, done_acts),
        "unallocated": unallocated,
        "fixed_block_notes": fixed_block_notes,
        "gap_summary": {
            "required_gap_count": len(gap["required_gaps"]),
            "bonus_gap_count": len(gap["bonus_gaps"]),
        },
    }
    plan["validation"] = validate_plan(plan, profile, act_by_id, list(done_acts))
    return plan


def _scheduled(activity: dict, hours: float, status: str) -> dict:
    return {
        "activity_id": activity["activity_id"],
        "name": activity["name"],
        "type": activity["type"],
        "workload_hours": hours,
        "covers_skills": activity["covers_skills"],
        "deliverable": activity["deliverable"],
        "acceptance": activity["acceptance"],
        "status": status,
    }


def _plan_recurring(ordered: list[dict], done: set, current: int) -> list[dict]:
    """为 recurring 活动计算每学期均摊工时。

    持续性任务（如刷题、英语备考）不适合一次性塞进某学期，而是把总工时
    均摊到其剩余窗口的每个学期，形成"每学期固定投入"的长期节奏。
    """
    out = []
    for a in ordered:
        if not a.get("recurring") or a["activity_id"] in done:
            continue
        lo, hi = a["semester_window"]
        start = max(current, lo)
        if start > hi:
            continue
        n_semesters = hi - start + 1
        per = round(a["workload_hours"] / n_semesters, 1)
        out.append({"activity_id": a["activity_id"], "per_semester": per})
    return out


def _include_prerequisites(target: list[dict], all_activities: list[dict],
                           done: set, target_family: str) -> list[dict]:
    """递归把先修活动加入候选（每个先修技能选工时最小的本族/both 活动）。"""
    chosen = {a["activity_id"]: a for a in target}
    queue = list(target)
    while queue:
        a = queue.pop()
        for prereq_skill in a["prerequisites"]:
            providers = sorted(
                [x for x in all_activities
                 if prereq_skill in x["covers_skills"]
                 and x["activity_id"] not in done
                 and x.get("relevant_family") in (target_family, "both")],
                key=lambda x: x["workload_hours"],
            )
            if providers and providers[0]["activity_id"] not in chosen:
                chosen[providers[0]["activity_id"]] = providers[0]
                queue.append(providers[0])
    return list(chosen.values())


def _topo_level(activity: dict, by_id: dict, target_family: str | None = None,
                mastered: set | None = None) -> int:
    """活动在本族/both 先修图中的拓扑层级（越大越靠后）。

    已掌握（mastered）的先修技能不构成待安排依赖，不增加层级。
    """
    mastered = mastered or set()
    levels = {}

    def allowed(x):
        return target_family is None or x.get("relevant_family") in (target_family, "both")

    def level(a, stack):
        aid = a["activity_id"]
        if aid in levels:
            return levels[aid]
        if aid in stack:  # 防御环
            return 0
        stack.add(aid)
        deps = []
        for skill in a["prerequisites"]:
            if skill in mastered:
                continue  # 已掌握，无需安排先修活动
            for x in by_id.values():
                if skill in x["covers_skills"] and allowed(x):
                    deps.append(level(x, stack))
                    break
        levels[aid] = 1 + (max(deps) if deps else 0)
        stack.discard(aid)
        return levels[aid]

    return level(activity, set())


def _prereq_done(a, scheduled_set, done, by_id) -> bool:
    for skill in a["prerequisites"]:
        ok = skill in set().union(*[set(by_id[x]["covers_skills"]) for x in scheduled_set | done]) if (scheduled_set | done) else False
        if not ok:
            return False
    return True


def _reason_unallocated(a: dict, semester_budget: float) -> str:
    if a["type"] == "internship":
        return "窗口内未找到先修就绪的暑期"
    if a["workload_hours"] > semester_budget:
        return "单学期工时超过当前时间预算"
    return "先修链或预算限制，剩余学期无法容纳"


# ============================================================
# 4. 近期 2-4 周任务
# ============================================================
def _near_term(profile: dict, semester_plans: list[dict], by_id: dict, done: set) -> dict:
    if not semester_plans:
        return {"weeks": []}
    first = semester_plans[0]
    activities_pool = [x for x in first["scheduled"] + first["fixed"]]
    weekly = float(profile["weekly_hours"])
    weeks = [{"week": i + 1, "tasks": [], "week_hours": 0} for i in range(NEAR_TERM_WEEKS)]

    for item in activities_pool:
        remaining = float(item["workload_hours"])
        for w in weeks:
            cap = weekly - w["week_hours"]
            if cap <= 0:
                continue
            put = min(cap, remaining)
            if put <= 0:
                continue
            w["tasks"].append({
                "activity_id": item["activity_id"],
                "task_name": item["name"],
                "skill_ids": item["covers_skills"],
                "hours": round(put, 1),
                "deliverable": item["deliverable"],
                "acceptance": item["acceptance"],
            })
            w["week_hours"] = round(w["week_hours"] + put, 1)
            remaining -= put
            if remaining <= 0:
                break
    return {"weeks": weeks, "note": "按当前学期计划拆解，每周任务不超过每周可投入时间"}


# ============================================================
# 5. 计划校验
# ============================================================
def validate_plan(plan: dict, profile: dict, by_id: dict,
                  completed_activity_ids: list[str] | None = None) -> dict:
    checks = []
    ok = True
    completed_activity_ids = completed_activity_ids or []

    # 预算检查
    for sp in plan["semester_plans"]:
        passed = sp["total_hours"] <= sp["budget_hours"] + 0.01
        ok = ok and passed
        checks.append({"check": f"第{sp['semester']}学期工时不超预算", "passed": passed,
                       "detail": f"{sp['total_hours']} / {sp['budget_hours']} 小时"})

    # 先修、窗口、去重
    seen = set()
    available = set(profile.get("mastered_skills", []))
    # 已完成活动覆盖的技能也视为可用
    for aid in completed_activity_ids:
        if aid in by_id:
            available.update(by_id[aid]["covers_skills"])

    for sp in plan["semester_plans"]:
        sem = sp["semester"]
        for item in sp["scheduled"] + sp["fixed"]:
            aid = item["activity_id"]
            a = by_id.get(aid)
            if not a:
                continue
            is_fixed = item["status"] == "fixed"
            is_recurring = item["status"] == "recurring"
            # 固定块（考研复习）与持续性任务（recurring）允许跨学期重复出现；普通活动不得重复
            if aid in seen and not is_fixed and not is_recurring:
                checks.append({"check": f"{aid} 无重复安排", "passed": False, "detail": aid})
                ok = False
            seen.add(aid)
            lo, hi = a["semester_window"]
            window_ok = lo <= sem <= hi
            ok = ok and window_ok
            checks.append({"check": f"{aid} 学期窗口", "passed": window_ok,
                           "detail": f"窗口[{lo},{hi}] 安排在{sem}"})
            prereq_ok = set(a["prerequisites"]).issubset(available)
            ok = ok and prereq_ok
            checks.append({"check": f"{aid} 先修成立", "passed": prereq_ok,
                           "detail": f"先修 {a['prerequisites']}"})
            available.update(a["covers_skills"])

    # 暑期块先修
    for blk in plan.get("summer_blocks", []):
        a = by_id.get(blk["activity_id"])
        if a:
            prereq_ok = set(a["prerequisites"]).issubset(available)
            ok = ok and prereq_ok
            checks.append({"check": f"{blk['activity_id']} 实习先修成立", "passed": prereq_ok,
                           "detail": f"暑期（第{blk['after_semester']}学期后）"})

    return {"passed": ok, "checks": checks}


# ============================================================
# 6. 版本差异
# ============================================================
def diff_plans(old: dict | None, new: dict) -> dict:
    def flatten(plan):
        m = {}
        for sp in plan["semester_plans"]:
            for item in sp["scheduled"] + sp["fixed"]:
                # recurring 活动跨学期，记录为学期集合
                if item["status"] == "recurring":
                    m.setdefault(item["activity_id"], set()).add(sp["semester"])
                else:
                    m[item["activity_id"]] = sp["semester"]
        for blk in plan.get("summer_blocks", []):
            m[blk["activity_id"]] = f"暑期{blk['after_semester']}"
        return m

    def _fmt(sem):
        return "第" + "、".join(str(s) for s in sorted(sem)) + "学期" if isinstance(sem, set) else sem

    old_map = flatten(old) if old else {}
    new_map = flatten(new)
    added, kept, deferred, removed = [], [], [], []
    for aid, sem in new_map.items():
        if aid not in old_map:
            added.append({"activity_id": aid, "semester": _fmt(sem)})
        elif old_map[aid] == sem:
            kept.append({"activity_id": aid, "semester": _fmt(sem)})
        else:
            deferred.append({"activity_id": aid, "from": _fmt(old_map[aid]), "to": _fmt(sem)})
    for aid, sem in old_map.items():
        if aid not in new_map:
            removed.append({"activity_id": aid, "semester": _fmt(sem)})

    impact = _impact_text(old, new)
    return {"added": added, "kept": kept, "deferred": deferred, "removed": removed, "impact": impact}


def _impact_text(old, new) -> str:
    if not old:
        return "首次生成计划，无历史版本对比。"
    op, np = old["profile_snapshot"], new["profile_snapshot"]
    parts = []
    if op.get("target_family") != np.get("target_family"):
        parts.append(f"目标岗位由 {op.get('target_family')} 切换为 {np.get('target_family')}，已重新分析缺口，已完成成果与可迁移能力保留")
    if op.get("weekly_hours") != np.get("weekly_hours"):
        parts.append(f"每周投入由 {op.get('weekly_hours')} 小时调整为 {np.get('weekly_hours')} 小时，预算重算，无法容纳的任务已延期或给出备选")
    if op.get("path") != np.get("path"):
        parts.append(f"发展路径由 {op.get('path')} 调整为 {np.get('path')}，时间侧重已改变")
    if not parts:
        parts.append("条件基本不变，按最新完成情况刷新计划。")
    return "；".join(parts)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
