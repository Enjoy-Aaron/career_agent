# -*- coding: utf-8 -*-
"""主 Agent：工具调用循环与运行记录。

闭环：读取状态 → 模型选择工具（模拟模式走规则路由）→ 程序校验并执行 →
结构化结果回传 → 继续判断或给出最终答复。

安全与边界：
- 工具白名单 + 参数 schema 校验 + 调用上限（MAX_STEPS），防止无限循环与
  越权调用；
- 所有调用（含页面按钮触发的 REST 调用）都经过 run_tool 并落盘，调用记录
  可在页面“Agent 记录”中完整展示；
- 系统提示词固定，资料中的指令无法改变系统规则；不执行模型生成的代码。
"""
import re

from .model_adapter import ModelError
from .schema import ValidationError
from .tools import BusinessTools, TOOL_DESCRIPTIONS

MAX_STEPS = 8

_SYSTEM_PROMPT = (
    "你是“岗位需求反推成长规划 Agent”，服务一名大学生。你只能通过白名单工具获取和处理数据，"
    "不能编造招聘要求、课程或活动。需要事实数据时先调用对应工具；工具返回错误时向用户说明并给出处理入口。"
    "技能频次仅作优先级参考、不等于硬门槛；没有证据的能力标注待评估。完成用户目标后用简洁中文总结。"
)

# 模拟模式意图路由（关键词 → 工具）
_INTENT_RULES = [
    ("add_custom_job", ("导入", "粘贴", "新增招聘")),
    ("analyze_jobs", ("分析", "招聘", "jd", "岗位要求")),
    ("get_gap", ("差距", "缺口", "短板")),
    ("match_activities", ("匹配", "对应", "课程", "活动库")),
    ("generate_plan", ("路线", "规划", "计划", "生成", "排")),
    ("export_report", ("报告", "导出")),
    ("get_state", ("状态", "现在情况", "进度")),
]


class AgentError(Exception):
    pass


class CareerAgent:
    def __init__(self, store, adapter, data_docs: dict):
        self.store = store
        self.adapter = adapter
        self.tools = BusinessTools(store, adapter, data_docs)
        self.logs = self.store.load_logs()

    # ---------- 统一工具执行（所有入口必经） ----------
    def run_tool(self, tool_name: str, arguments: dict, trigger: str = "page") -> dict:
        if len(self.logs["records"]) >= 10000:
            self.logs["records"] = self.logs["records"][-5000:]
        seq = len(self.logs["records"]) + 1
        record = {"seq": seq, "trigger": trigger, "tool_name": tool_name,
                  "arguments": arguments, "ok": False, "at": _now(),
                  "model_mode": self.adapter.status()["mode"]}
        try:
            result = self.tools.dispatch(tool_name, arguments)
            record["ok"] = bool(result.get("ok", True))
            record["result_summary"] = _summarize(result)
            self.logs["records"].append(record)
            self.store.save_logs(self.logs)
            return result
        except (ValidationError, ModelError) as e:
            record["error"] = getattr(e, "errors", None) or str(e)
            self.logs["records"].append(record)
            self.store.save_logs(self.logs)
            msg = getattr(e, "errors", None) or [str(e)]
            return {"ok": False, "error": msg, "recoverable": True}

    def get_records(self) -> list[dict]:
        return self.store.load_logs()["records"]

    # ---------- 自然语言闭环 ----------
    def chat(self, user_message: str) -> dict:
        messages = [{"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}]
        steps = 0
        trace = []
        try:
            while steps < MAX_STEPS:
                steps += 1
                if self.adapter.is_mock:
                    decision = self._route_by_rules(user_message if steps == 1 else trace)
                else:
                    decision = self.adapter.select_tool(messages, TOOL_DESCRIPTIONS)
                if "final_answer" in decision:
                    return {"ok": True, "answer": decision["final_answer"], "trace": trace}
                tool_name = decision["tool_name"]
                args = decision.get("arguments", {})
                result = self.run_tool(tool_name, args, trigger="chat")
                trace.append({"step": steps, "tool_name": tool_name, "ok": result.get("ok"),
                              "error": result.get("error") or result.get("message") or ""})
                messages.append({"role": "assistant", "content": None,
                                 "tool_calls": [{"function": {"name": tool_name,
                                                              "arguments": _json(args)}}]})
                messages.append({"role": "tool", "name": tool_name,
                                 "content": _json(result)})
                if not result.get("ok"):
                    detail = result.get("error") or result.get("message") or "未知错误"
                    return {"ok": False, "answer": "工具执行出错：" + _json(detail),
                            "trace": trace}
                if self.adapter.is_mock:
                    # 模拟模式：路由执行完所有识别到的意图后总结
                    if steps >= len(self._intents(user_message)):
                        return {"ok": True, "answer": self._mock_summary(user_message, trace),
                                "trace": trace}
            return {"ok": False, "answer": f"已达到调用上限 {MAX_STEPS} 步，任务未完成，请缩小请求范围。",
                    "trace": trace}
        except ModelError as e:
            return {"ok": False, "answer": f"模型调用失败：{e}。可在配置中切换为模拟模式继续。",
                    "trace": trace, "model_error": True}

    # ---------- 模拟模式规则路由 ----------
    def _intents(self, message: str) -> list[str]:
        low = message.lower()
        found = []
        for tool_name, kws in _INTENT_RULES:
            if any(k in low for k in kws):
                found.append(tool_name)
        return found

    def _route_by_rules(self, payload) -> dict:
        if isinstance(payload, str):
            intents = self._intents(payload)
            if not intents:
                return {"final_answer": "我可以帮你分析招聘、评估能力差距、匹配课程活动、生成学期路线或调整计划，告诉我你想先做哪一步？"}
            self._mock_queue = intents[1:]
            return {"tool_name": intents[0], "arguments": {}}
        if getattr(self, "_mock_queue", None):
            return {"tool_name": self._mock_queue.pop(0), "arguments": {}}
        return {"final_answer": "已完成。"}

    def _mock_summary(self, message: str, trace: list[dict]) -> str:
        tools_used = "、".join(t["tool_name"] for t in trace)
        return f"[模拟模式] 已按规则路由完成：{tools_used}。切换为本地/云端模型后，工具选择由模型完成，但归一、计数、工时与校验仍由程序执行。"


# ---------- 工具函数 ----------
def _summarize(result: dict, max_len: int = 160) -> str:
    keep = {k: v for k, v in result.items() if k not in ("aggregate", "report_markdown", "matches")}
    text = _json(keep)
    return text[:max_len]


def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
