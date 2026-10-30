# -*- coding: utf-8 -*-
"""业务工具层：主 Agent 白名单可调用的全部函数。

每个工具：
- 在 TOOL_SPECS 登记参数 schema，模型给出的参数先校验后执行；
- 只做确定性业务处理并返回结构化字段；
- 不执行模型生成的代码，不接受资料中的指令改变规则。

工具白名单：
  analyze_jobs        招聘要求提取与技能归类
  get_aggregate       查看聚合频次
  get_gap             学生画像与能力差距
  match_activities    缺口到课程/实践的映射与推荐依据
  generate_plan       生成并校验学期路线（通过后才成为可采用版本）
  update_completion   记录任务完成情况
  add_custom_job      粘贴/导入新的招聘文本
  import_jobs         批量导入多条招聘（JSON 数组）
  fetch_job_from_url  从 URL 抓取招聘正文入库
  adjust_conditions   改变岗位/时间/路径并重规划，输出版本差异
  export_report       导出成长报告（Markdown）
  get_state           读取当前状态摘要
"""
import html
import re
import urllib.error
import urllib.request

from . import planner
from .schema import ValidationError, validate
from .storage import StateStore

TOOL_SPECS = {
    "analyze_jobs": {
        "family": {"type": "str"},
    },
    "get_aggregate": {},
    "get_gap": {},
    "match_activities": {
        "only_required": {"type": "bool"},
    },
    "generate_plan": {},
    "update_completion": {
        "activity_id": {"type": "str", "required": True},
        "note": {"type": "str"},
        "evidence": {"type": "str"},
    },
    "add_custom_job": {
        "raw_text": {"type": "str", "required": True},
        "family": {"type": "str", "required": True},
        "title": {"type": "str"},
        "company": {"type": "str"},
        "source_url": {"type": "str"},
    },
    "import_jobs": {
        "items": {"type": "list", "required": True, "item": {"type": "dict"}},
    },
    "fetch_job_from_url": {
        "url": {"type": "str", "required": True},
        "family": {"type": "str", "required": True},
    },
    "add_custom_family": {
        "family": {"type": "str", "required": True},
        "label": {"type": "str", "required": True},
    },
    "adjust_conditions": {
        "target_family": {"type": "str"},
        "weekly_hours": {"type": "float", "min": 0, "max": 80},
        "path": {"type": "str", "enum": ["employment", "postgraduate", "recommendation"]},
    },
    "export_report": {},
    "get_state": {},
}

# 供模型 function calling 的工具描述（OpenAI tools 格式）
TOOL_DESCRIPTIONS = [
    {"type": "function", "function": {
        "name": "analyze_jobs",
        "description": "对真实招聘文本提取技能、学历、经验与通用能力，同义词归一、去重并按去重招聘数统计，必须与加分分开。",
        "parameters": {"type": "object", "properties": {
            "family": {"type": "string", "description": "岗位族，默认 all；可用 backend / ai 或已登记的自定义族"}}}}},
    {"type": "function", "function": {
        "name": "get_gap",
        "description": "基于学生画像与目标岗位聚合，输出硬性缺口、加分缺口、待评估能力与学历提示。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "match_activities",
        "description": "把能力缺口匹配到课程、项目、竞赛、实习等活动，给出先修、工时、交付物与推荐依据。",
        "parameters": {"type": "object", "properties": {
            "only_required": {"type": "boolean", "description": "是否只看硬性缺口"}}}}},
    {"type": "function", "function": {
        "name": "generate_plan",
        "description": "生成剩余学期路线与未来四周任务，程序校验预算、先修、窗口与去重，通过后才保存为可采用版本。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "update_completion",
        "description": "记录某活动/任务已完成，保留成果证据（evidence），覆盖技能自动提升为已掌握，重规划时作为可迁移能力。",
        "parameters": {"type": "object", "properties": {
            "activity_id": {"type": "string"}, "note": {"type": "string"}, "evidence": {"type": "string"}},
            "required": ["activity_id"]}}},
    {"type": "function", "function": {
        "name": "add_custom_job",
        "description": "粘贴或导入新的招聘文本并登记来源，随后可调用 analyze_jobs 分析。family 需为预置族或已登记的自定义族。",
        "parameters": {"type": "object", "properties": {
            "raw_text": {"type": "string"}, "family": {"type": "string"},
            "title": {"type": "string"}, "company": {"type": "string"}, "source_url": {"type": "string"}},
            "required": ["raw_text", "family"]}}},
    {"type": "function", "function": {
        "name": "add_custom_family",
        "description": "登记一个新的岗位族（如 前端、测试、数据），之后可为其添加招聘并独立分析。",
        "parameters": {"type": "object", "properties": {
            "family": {"type": "string"}, "label": {"type": "string"}},
            "required": ["family", "label"]}}},
    {"type": "function", "function": {
        "name": "import_jobs",
        "description": "批量导入多条招聘（items 为数组，每项含 raw_text、family 及可选 title/company/source_url），返回成功与失败明细。",
        "parameters": {"type": "object", "properties": {
            "items": {"type": "array", "items": {"type": "object"}}},
            "required": ["items"]}}},
    {"type": "function", "function": {
        "name": "fetch_job_from_url",
        "description": "从 URL 抓取招聘页正文并入库（标准库实现，尽力而为，失败时提示改用手动粘贴）。",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}, "family": {"type": "string"}},
            "required": ["url", "family"]}}},
    {"type": "function", "function": {
        "name": "adjust_conditions",
        "description": "改变目标岗位、每周时间或就业/考研/保研路径，保留已完成记录，重算计划并输出版本差异。",
        "parameters": {"type": "object", "properties": {
            "target_family": {"type": "string"},
            "weekly_hours": {"type": "number"},
            "path": {"type": "string", "enum": ["employment", "postgraduate", "recommendation"]}}}}},
    {"type": "function", "function": {
        "name": "export_report",
        "description": "导出 Markdown 成长报告，含岗位分析、差距、路线、四周任务与版本差异。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_state",
        "description": "读取当前画像、计划版本、完成情况与模型模式的状态摘要。",
        "parameters": {"type": "object", "properties": {}}}},
]


PRESET_FAMILIES = ("backend", "ai")


class BusinessTools:
    def __init__(self, store: StateStore, adapter, data_docs: dict):
        self.store = store
        self.adapter = adapter
        self.jobs_doc = data_docs["jobs"]
        self.courses_doc = data_docs["courses"]
        self.activities_doc = data_docs["activities"]

    # ---------- 岗位族（预置 + 自定义） ----------
    def _known_families(self) -> list[str]:
        custom = self.store.load_custom_families().get("families", [])
        return list(PRESET_FAMILIES) + [f["family"] for f in custom]

    def _ensure_family_known(self, family: str) -> None:
        if family not in self._known_families():
            raise ValidationError([
                f"岗位族 {family!r} 未知，可用：{', '.join(self._known_families())}；"
                "如需新岗位族请先调用 add_custom_family 登记"])

    def _t_add_custom_family(self, args: dict) -> dict:
        doc = self.store.load_custom_families()
        family = args["family"].strip()
        if family in PRESET_FAMILIES:
            raise ValidationError([f"岗位族 {family!r} 是预置族，无需重复登记"])
        if not family:
            raise ValidationError(["岗位族标识不能为空"])
        for f in doc["families"]:
            if f["family"] == family:
                raise ValidationError([f"岗位族 {family!r} 已登记"])
        doc["families"].append({"family": family, "label": args["label"].strip()})
        self.store.save_custom_families(doc)
        return {"ok": True, "family": family,
                "message": f"岗位族 {family}（{args['label']}）已登记，可为其添加招聘并分析"}

    # ---------- 统一分发 ----------
    def dispatch(self, tool_name: str, arguments: dict) -> dict:
        if tool_name not in TOOL_SPECS:
            raise ValidationError([f"工具 {tool_name} 不在白名单内"])
        validate(arguments or {}, TOOL_SPECS[tool_name])
        handler = getattr(self, f"_t_{tool_name}")
        return handler(arguments or {})

    # ---------- 工具实现 ----------
    def _all_jobs(self) -> list[dict]:
        custom = self.store.load_custom_jobs().get("jobs", [])
        return self.jobs_doc["jobs"] + custom

    def _t_add_custom_job(self, args: dict) -> dict:
        self._ensure_family_known(args["family"])
        custom_doc = self.store.load_custom_jobs()
        next_id = f"J{100 + len(custom_doc['jobs']) + 1}"
        job = {
            "job_id": next_id,
            "family": args["family"],
            "title": args.get("title", "自定义招聘"),
            "company": args.get("company", "未注明"),
            "source_name": "用户粘贴导入",
            "source_url": args.get("source_url", ""),
            "location": "",
            "salary": "",
            "job_type": "campus",
            "raw_text": args["raw_text"],
            "fetched_date": planner._now()[:10],
            "fetched_at": planner._now(),
            "fetch_method": "manual",
        }
        custom_doc["jobs"].append(job)
        self.store.save_custom_jobs(custom_doc)
        return {"ok": True, "job_id": next_id, "message": "招聘文本已登记，可调用 analyze_jobs 分析"}

    def _t_import_jobs(self, args: dict) -> dict:
        """批量导入多条招聘（JSON 数组），逐条校验并入库，返回成功/失败明细。"""
        custom_doc = self.store.load_custom_jobs()
        ok_list, fail_list = [], []
        for idx, item in enumerate(args["items"]):
            raw = str(item.get("raw_text", "")).strip()
            family = item.get("family", "")
            if not raw or not family:
                fail_list.append({"index": idx, "reason": "缺少 raw_text 或 family"})
                continue
            try:
                self._ensure_family_known(family)
            except ValidationError as e:
                fail_list.append({"index": idx, "reason": "; ".join(e.errors)})
                continue
            next_id = f"J{100 + len(custom_doc['jobs']) + 1}"
            custom_doc["jobs"].append({
                "job_id": next_id, "family": family,
                "title": item.get("title", "批量导入招聘"),
                "company": item.get("company", "未注明"),
                "source_name": item.get("source_name", "批量导入"),
                "source_url": item.get("source_url", ""),
                "location": item.get("location", ""),
                "salary": item.get("salary", ""),
                "job_type": "campus",
                "raw_text": raw,
                "fetched_date": planner._now()[:10],
                "fetched_at": planner._now(),
                "fetch_method": "import",
            })
            ok_list.append(next_id)
        self.store.save_custom_jobs(custom_doc)
        return {"ok": True, "imported": len(ok_list), "failed": len(fail_list),
                "job_ids": ok_list, "failures": fail_list,
                "message": f"批量导入完成：成功 {len(ok_list)} 条，失败 {len(fail_list)} 条"}

    def _t_fetch_job_from_url(self, args: dict) -> dict:
        """从 URL 抓取招聘页正文并入库（标准库 urllib，尽力而为，失败降级）。"""
        self._ensure_family_known(args["family"])
        url = args["url"].strip()
        if not url.startswith(("http://", "https://")):
            raise ValidationError(["url 需以 http:// 或 https:// 开头"])
        text = _fetch_text_from_url(url, timeout=15)
        if not text or len(text) < 20:
            return {"ok": False, "message": "未能从该地址提取到有效正文，请改用「粘贴导入」手动登记",
                    "url": url}
        custom_doc = self.store.load_custom_jobs()
        next_id = f"J{100 + len(custom_doc['jobs']) + 1}"
        custom_doc["jobs"].append({
            "job_id": next_id, "family": args["family"],
            "title": "URL 抓取招聘", "company": "未注明",
            "source_name": "URL 自动抓取", "source_url": url,
            "location": "", "salary": "", "job_type": "campus",
            "raw_text": text,
            "fetched_date": planner._now()[:10],
            "fetched_at": planner._now(),
            "fetch_method": "fetch",
        })
        self.store.save_custom_jobs(custom_doc)
        return {"ok": True, "job_id": next_id, "url": url,
                "text_length": len(text),
                "message": f"已抓取并登记 {next_id}，共 {len(text)} 字，可调用 analyze_jobs 分析"}

    def _t_analyze_jobs(self, args: dict) -> dict:
        family = args.get("family", "all")
        if family != "all":
            self._ensure_family_known(family)
        jobs = self._all_jobs()
        if family != "all":
            jobs = [j for j in jobs if j["family"] == family]
        extractions = []
        for j in jobs:
            extractions.append(self.adapter.extract_job(j["raw_text"], j["job_id"]))
        meta = {"jobs": jobs}
        aggregate = planner.aggregate_analysis(extractions, meta)
        analysis = {"extractions": extractions, "aggregate": aggregate,
                    "analyzed_at": planner._now(), "mode_status": self.adapter.status()}
        self.store.save_analysis(analysis)
        return {"ok": True, "analyzed_jobs": len(jobs),
                "families": [{"family": f["family"], "job_count": f["job_count"],
                              "top_skills": [s["name"] for s in f["skills"][:5]]}
                             for f in aggregate["families"]],
                "mode_status": self.adapter.status()}

    def _t_get_aggregate(self, args: dict) -> dict:
        analysis = self.store.load_analysis()
        if not analysis:
            return {"ok": False, "message": "尚未分析招聘，请先调用 analyze_jobs"}
        return {"ok": True, "aggregate": analysis["aggregate"]}

    def _t_get_gap(self, args: dict) -> dict:
        profile = self.store.load_profile()
        analysis = self.store.load_analysis()
        if not profile or not analysis:
            return {"ok": False, "message": "缺少画像或招聘分析，请先建档并分析"}
        gap = planner.gap_analysis(profile, analysis["aggregate"])
        return {"ok": True, "gap": gap}

    def _t_match_activities(self, args: dict) -> dict:
        profile = self.store.load_profile()
        analysis = self.store.load_analysis()
        if not profile or not analysis:
            return {"ok": False, "message": "缺少画像或招聘分析"}
        gap = planner.gap_analysis(profile, analysis["aggregate"])
        gap_ids = {s["skill_id"] for s in gap["required_gaps"]}
        if not args.get("only_required", False):
            gap_ids |= {s["skill_id"] for s in gap["bonus_gaps"]}
        matches = []
        for a in self.activities_doc["activities"]:
            hit = gap_ids.intersection(a["covers_skills"])
            if not hit:
                continue
            matches.append({
                "activity_id": a["activity_id"], "name": a["name"], "type": a["type"],
                "covers_skills": a["covers_skills"], "prerequisites": a["prerequisites"],
                "semester_window": a["semester_window"], "workload_hours": a["workload_hours"],
                "deliverable": a["deliverable"], "acceptance": a["acceptance"],
                "recommendation_basis": f"覆盖缺口技能 {sorted(hit)}；来源：{a['source']}",
            })
        return {"ok": True, "matches": matches,
                "course_basis": {"source": self.courses_doc["source"],
                                 "note": "课内课程作为能力证据，不占课外工时，详见课程库"}}

    def _completed_ids(self) -> list[str]:
        return list(self.store.load_tasks().get("completions", {}).keys())

    def _t_generate_plan(self, args: dict) -> dict:
        profile = self.store.load_profile()
        analysis = self.store.load_analysis()
        if not profile or not analysis:
            return {"ok": False, "message": "缺少画像或招聘分析"}
        gap = planner.gap_analysis(profile, analysis["aggregate"])
        plans_doc = self.store.load_plans()
        version = len(plans_doc["versions"]) + 1
        plan = planner.build_plan(profile, gap, self.activities_doc, self._completed_ids(), version)
        if not plan["validation"]["passed"]:
            return {"ok": False, "message": "计划未通过规则校验，未保存为可采用版本",
                    "validation": plan["validation"]}
        diff = planner.diff_plans(
            plans_doc["versions"][-1] if plans_doc["versions"] else None, plan)
        plan["diff_from_previous"] = diff
        plans_doc["versions"].append(plan)
        self.store.save_plans(plans_doc)
        return {"ok": True, "plan_id": plan["plan_id"], "version": version,
                "semesters": len(plan["semester_plans"]),
                "unallocated_count": len(plan["unallocated"]), "diff": diff}

    def _t_update_completion(self, args: dict) -> dict:
        tasks = self.store.load_tasks()
        aid = args["activity_id"]
        record = {"done_at": planner._now(), "note": args.get("note", ""),
                  "evidence": args.get("evidence", "")}
        tasks["completions"][aid] = record
        self.store.save_tasks(tasks)
        # 完成活动覆盖的技能 → 自动提升为已掌握，并记录证据来源
        promoted = []
        act = next((a for a in self.activities_doc["activities"] if a["activity_id"] == aid), None)
        if act:
            profile = self.store.load_profile() or {}
            mastered = set(profile.get("mastered_skills", []))
            pending = set(profile.get("pending_skills", []))
            evidence = dict(profile.get("skill_evidence", {}))
            for sid in act["covers_skills"]:
                mastered.add(sid)
                pending.discard(sid)
                ev = args.get("evidence") or f"完成活动「{act['name']}」"
                evidence[sid] = ev
                promoted.append(sid)
            profile["mastered_skills"] = sorted(mastered)
            profile["pending_skills"] = sorted(pending)
            profile["skill_evidence"] = evidence
            self.store.save_profile(profile)
        return {"ok": True, "activity_id": aid,
                "promoted_skills": promoted,
                "message": "完成情况已记录，覆盖能力已标记为已掌握并附证据，重规划时保留并计入可迁移能力"}

    def _t_adjust_conditions(self, args: dict) -> dict:
        profile = self.store.load_profile()
        if not profile:
            return {"ok": False, "message": "尚未建档"}
        if args.get("target_family") is not None:
            self._ensure_family_known(args["target_family"])
        for key in ("target_family", "weekly_hours", "path"):
            if key in args and args[key] is not None:
                profile[key] = args[key]
        self.store.save_profile(profile)

        analysis = self.store.load_analysis()
        gap = planner.gap_analysis(profile, analysis["aggregate"])
        plans_doc = self.store.load_plans()
        old = plans_doc["versions"][-1] if plans_doc["versions"] else None
        version = len(plans_doc["versions"]) + 1
        plan = planner.build_plan(profile, gap, self.activities_doc, self._completed_ids(), version)
        if not plan["validation"]["passed"]:
            return {"ok": False, "message": "调整后计划未通过校验，未保存",
                    "validation": plan["validation"]}
        diff = planner.diff_plans(old, plan)
        plan["diff_from_previous"] = diff
        plans_doc["versions"].append(plan)
        self.store.save_plans(plans_doc)
        return {"ok": True, "version": version, "diff": diff,
                "unallocated_count": len(plan["unallocated"])}

    def _t_export_report(self, args: dict) -> dict:
        profile = self.store.load_profile()
        analysis = self.store.load_analysis()
        plans_doc = self.store.load_plans()
        if not profile or not analysis or not plans_doc["versions"]:
            return {"ok": False, "message": "资料不足，无法导出报告"}
        report = self._render_report(profile, analysis, plans_doc)
        return {"ok": True, "report_markdown": report,
                "filename": f"成长报告_{planner._now()[:10]}.md"}

    def _t_get_state(self, args: dict) -> dict:
        plans_doc = self.store.load_plans()
        return {
            "ok": True,
            "profile": self.store.load_profile(),
            "model_status": self.adapter.status(),
            "plan_versions": len(plans_doc["versions"]),
            "latest_plan": plans_doc["versions"][-1]["plan_id"] if plans_doc["versions"] else None,
            "completions": self._completed_ids(),
            "custom_jobs": len(self.store.load_custom_jobs().get("jobs", [])),
        }

    # ---------- 报告渲染 ----------
    def _render_report(self, profile, analysis, plans_doc) -> str:
        plan = plans_doc["versions"][-1]
        lines = [
            "# 大学生职业成长报告",
            f"生成时间：{planner._now()}　模型模式：{self.adapter.status()['mode']}",
            "",
            "## 一、学生画像",
            f"- 专业：{profile['major']}；当前学期：第 {profile['semester']} 学期",
            f"- 目标岗位族：{profile['target_family']}；发展路径：{profile['path']}",
            f"- 每周课外可投入：{profile['weekly_hours']} 小时",
            f"- 已掌握技能：{', '.join(profile.get('mastered_skills', [])) or '（待补充）'}",
            "",
            "## 二、岗位需求证据（真实招聘）",
        ]
        for fam in analysis["aggregate"]["families"]:
            lines.append(f"### {fam['family']}（{fam['job_count']} 条招聘）")
            for s in fam["skills"][:10]:
                src = s["evidence"][0]["source_url"]
                lines.append(f"- {s['name']}：硬性 {s['required_count']} 次、加分 {s['bonus_count']} 次；来源：{src}")
        lines += ["", "## 三、能力差距",
                  f"- 硬性缺口 {plan['gap_summary']['required_gap_count']} 项，加分缺口 {plan['gap_summary']['bonus_gap_count']} 项"]
        # 职业规划思考：学历门槛 → 分路径时间分配建议
        gap = planner.gap_analysis(profile, analysis["aggregate"])
        if gap.get("path_advice"):
            pa = gap["path_advice"]
            lines += ["", "## 四、职业规划思考（就业 / 考研 / 保研如何改变时间分配）",
                      f"- 学历门槛评估：{pa['summary']}"]
            for s in pa["suggestions"]:
                mark = " ← 当前路径" if s["path"] == pa.get("current_path") else ""
                lines.append(f"- 【{s['label']}】{s['advice']}{mark}")
        lines += ["", "## 五、分学期路线"]
        for sp in plan["semester_plans"]:
            lines.append(f"### 第 {sp['semester']} 学期（预算 {sp['budget_hours']} 小时，安排 {sp['total_hours']} 小时）")
            for item in sp["scheduled"] + sp["fixed"]:
                lines.append(f"- {item['name']}（{item['workload_hours']}h）交付：{item['deliverable']}；验收：{item['acceptance']}")
        for blk in plan["summer_blocks"]:
            lines.append(f"- 暑期（第{blk['after_semester']}学期后）：{blk['name']}（{blk['workload_hours']}h）")
        lines += ["", "## 六、未来四周任务"]
        for w in plan["near_term"]["weeks"]:
            t = "；".join(f"{x['task_name']}({x['hours']}h)" for x in w["tasks"]) or "无"
            lines.append(f"- 第 {w['week']} 周：{t}")
        if plan.get("diff_from_previous"):
            d = plan["diff_from_previous"]
            lines += ["", "## 七、版本差异",
                      f"- 新增 {len(d['added'])}、保留 {len(d['kept'])}、延期 {len(d['deferred'])}、移除 {len(d['removed'])}",
                      f"- 影响：{d['impact']}"]
        lines += ["", "> 说明：技能频次仅作优先级参考，不等于硬门槛；所有结论均附招聘来源，缺失依据处标注待补充，不做事实伪装。"]
        return "\n".join(lines)


# ============================================================
# URL 正文提取（标准库实现，尽力而为）
# ============================================================
_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def _fetch_text_from_url(url: str, timeout: int = 15) -> str:
    """抓取 URL 并提取可见正文文本。

    只依赖标准库 urllib：去 script/style/标签 → HTML 实体反转义 →
    压缩空白。对不同网站结构鲁棒性有限，属于"尽力而为"的辅助采集，
    失败或正文过短时由上层提示改用手动粘贴。
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (CareerAgent/1.0; educational analysis)",
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return ""
    raw = _TAG_RE.sub("\n", raw)
    text = html.unescape(raw)
    text = _WS_RE.sub("\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
    return text
