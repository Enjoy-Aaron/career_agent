# -*- coding: utf-8 -*-
"""轻量数据持久化（零依赖，JSON 文件 + 原子写入）。

业务状态不依赖聊天记录：画像、招聘分析、计划版本、任务完成情况与 Agent
调用记录全部落盘，重启应用后可完整恢复。写入采用“临时文件 + os.replace”
原子替换，避免中途断电/异常产生半截文件。
"""
import json
import os
import tempfile
from typing import Any


def load_json(path: str, default: Any = None) -> Any:
    """读取 JSON；文件不存在时返回 default。"""
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_atomic(path: str, data: Any) -> None:
    """原子写入 JSON（UTF-8、保留中文、两空格缩进）。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


class StateStore:
    """统一管理 state 目录下的全部业务状态文件。"""

    def __init__(self, state_dir: str):
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.profile_path = os.path.join(state_dir, "profile.json")
        self.analysis_path = os.path.join(state_dir, "job_analysis.json")
        self.plans_path = os.path.join(state_dir, "plans.json")
        self.tasks_path = os.path.join(state_dir, "tasks.json")
        self.logs_path = os.path.join(state_dir, "agent_logs.json")
        self.custom_jobs_path = os.path.join(state_dir, "custom_jobs.json")
        self.custom_families_path = os.path.join(state_dir, "custom_families.json")

    # ---- 画像 ----
    def load_profile(self) -> dict | None:
        return load_json(self.profile_path)

    def save_profile(self, profile: dict) -> None:
        save_json_atomic(self.profile_path, profile)

    # ---- 招聘分析结果 ----
    def load_analysis(self) -> dict | None:
        return load_json(self.analysis_path)

    def save_analysis(self, analysis: dict) -> None:
        save_json_atomic(self.analysis_path, analysis)

    # ---- 计划版本 ----
    def load_plans(self) -> dict:
        return load_json(self.plans_path, {"versions": []})

    def save_plans(self, plans: dict) -> None:
        save_json_atomic(self.plans_path, plans)

    # ---- 任务完成情况 ----
    def load_tasks(self) -> dict:
        return load_json(self.tasks_path, {"completions": {}})

    def save_tasks(self, tasks: dict) -> None:
        save_json_atomic(self.tasks_path, tasks)

    # ---- Agent 调用记录 ----
    def load_logs(self) -> dict:
        return load_json(self.logs_path, {"records": []})

    def save_logs(self, logs: dict) -> None:
        save_json_atomic(self.logs_path, logs)

    # ---- 用户粘贴/导入的自定义招聘 ----
    def load_custom_jobs(self) -> dict:
        return load_json(self.custom_jobs_path, {"jobs": []})

    def save_custom_jobs(self, jobs: dict) -> None:
        save_json_atomic(self.custom_jobs_path, jobs)

    # ---- 用户登记的自定义岗位族 ----
    def load_custom_families(self) -> dict:
        return load_json(self.custom_families_path, {"families": []})

    def save_custom_families(self, families: dict) -> None:
        save_json_atomic(self.custom_families_path, families)
