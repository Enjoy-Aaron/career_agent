# -*- coding: utf-8 -*-
"""结构化字段校验工具（零依赖，替代 pydantic 的最小实现）。

用于校验模型返回内容与 Agent 工具参数：必填字段、类型、枚举与取值范围。
模型返回的任何字段都必须先通过校验，才能进入业务计算；校验失败抛出
ValidationError，由主 Agent 转换为可理解的错误，不允许带病数据落库。
"""
from typing import Any, Iterable


class ValidationError(Exception):
    """结构化校验失败。errors 为可读的字段级错误列表。"""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("；".join(self.errors))


# 类型名 -> Python 类型
_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
}


def validate(data: Any, spec: dict, path: str = "") -> dict:
    """按 spec 校验 data，返回通过校验的数据（原样返回，不做静默转换）。

    spec 示例：
    {
      "name": {"type": "str", "required": True},
      "age":  {"type": "int", "min": 0, "max": 120},
      "path": {"type": "str", "enum": ["employment", "postgraduate"]},
      "skills": {"type": "list", "item": {"type": "str"}},
    }
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValidationError([f"{path or 'root'}：期望对象(dict)，实际为 {type(data).__name__}"])

    for field, rule in spec.items():
        full = f"{path}.{field}" if path else field
        required = rule.get("required", False)
        if field not in data or data[field] is None:
            if required:
                errors.append(f"{full}：缺少必填字段")
            continue

        value = data[field]
        type_name = rule.get("type")
        if type_name:
            expected = _TYPE_MAP.get(type_name)
            # bool 是 int 的子类，需显式区分
            if type_name in ("int", "float") and isinstance(value, bool):
                errors.append(f"{full}：期望 {type_name}，实际为 bool")
            elif expected and not isinstance(value, expected):
                errors.append(f"{full}：期望 {type_name}，实际为 {type(value).__name__}")
                continue

        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"{full}：取值 {value!r} 不在允许集合 {rule['enum']}")
        if "min" in rule and isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < rule["min"]:
                errors.append(f"{full}：{value} 小于最小值 {rule['min']}")
        if "max" in rule and isinstance(value, (int, float)) and not isinstance(value, bool):
            if value > rule["max"]:
                errors.append(f"{full}：{value} 大于最大值 {rule['max']}")

        if "item" in rule and isinstance(value, list):
            for idx, item in enumerate(value):
                try:
                    validate({"_": item}, {"_": rule["item"]}, path=full)
                except ValidationError as exc:
                    errors.extend(f"{full}[{idx}] {e}" for e in exc.errors)

    if errors:
        raise ValidationError(errors)
    return data


# ---- 常用业务 spec ----

PROFILE_SPEC = {
    "major": {"type": "str", "required": True},
    "semester": {"type": "int", "required": True, "min": 1, "max": 8},
    "target_family": {"type": "str", "required": True},
    "weekly_hours": {"type": "float", "required": True, "min": 0, "max": 80},
    "path": {"type": "str", "required": True, "enum": ["employment", "postgraduate", "recommendation"]},
    "mastered_skills": {"type": "list", "item": {"type": "str"}},
    "pending_skills": {"type": "list", "item": {"type": "str"}},
    "skill_evidence": {"type": "dict"},
}

TOOL_CALL_SPEC = {
    "tool_name": {"type": "str", "required": True},
    "arguments": {"type": "dict", "required": True},
}
