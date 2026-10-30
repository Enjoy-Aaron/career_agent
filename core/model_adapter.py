# -*- coding: utf-8 -*-
"""大模型适配层（零依赖，urllib 实现 OpenAI 兼容协议）。

三种运行模式：
  - mock       模拟模式：规则实现，确定性、可复现，无需任何网络与密钥；
  - local      本地模型：对接 Ollama 等提供 /v1/chat/completions 的本地服务；
  - cloud      云端模型：对接任意 OpenAI 兼容接口，密钥仅保存在本地配置。

设计原则：
1. 系统提示词固定，招聘资料只作为数据字段传入，资料中的任何文字都不能
   修改系统规则（提示注入防护）；
2. 模型只负责“理解”，归一、计数、工时、依赖、版本等可验证计算一律由
   程序完成；模型输出与模拟输出走同一个归一函数，规则不被模型绕过；
3. 不执行模型生成的任何代码；模型失败抛出 ModelError，由上层给出可理解
   的错误或明确的模拟模式标记，绝不把模拟结果伪装成真实模型结果。
"""
import json
import re
import urllib.error
import urllib.request
from typing import Any

from .schema import ValidationError, validate

# 句子切分：中文句末标点、换行、分号列表
_SENTENCE_SPLIT = re.compile(r"[。\n；;]")
# 加分/优先语境关键词
_BONUS_MARKERS = ("加分", "优先", "为佳", "亮点", "优先录用", "者优先")
# 学历关键词
_DEGREE_MASTER = ("硕士及以上", "硕士或博士", "硕士，博士", "硕士,博士")
_DEGREE_BACHELOR = ("本科及以上", "本科或硕士", "本科,硕士")


class ModelError(Exception):
    """模型调用失败（网络、协议、鉴权或返回格式问题）。"""


def _load_taxonomy(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class ModelAdapter:
    """统一模型适配层。"""

    def __init__(self, config: dict, taxonomy_path: str):
        self.config = config or {}
        self.mode = self.config.get("mode", "mock")
        if self.mode not in ("mock", "local", "cloud"):
            raise ModelError(f"未知模型模式：{self.mode}")
        self.taxonomy = _load_taxonomy(taxonomy_path)
        self._build_matchers()
        self.timeout = float(self.config.get("timeout_seconds", 60))
        self.fallback_to_mock = bool(self.config.get("fallback_to_mock", False))

    # ---------- 匹配器构建 ----------
    def _build_matchers(self) -> None:
        """为每个技能构建别名匹配器：英文走词边界，中文走子串。"""
        self.matchers: list[dict] = []
        for skill in self.taxonomy["skills"]:
            patterns = []
            for alias in skill["aliases"]:
                if re.search(r"[A-Za-z]", alias):
                    patterns.append(re.compile(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", re.IGNORECASE))
                else:
                    patterns.append(re.compile(re.escape(alias)))
            self.matchers.append({"skill": skill, "patterns": patterns})

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "model": self.config.get("model", "mock-rules" if self.mode == "mock" else "未配置"),
            "base_url": self.config.get("base_url", ""),
            "is_mock": self.is_mock,
        }

    # ---------- 招聘提取 ----------
    def extract_job(self, raw_text: str, job_id: str) -> dict:
        """提取单条招聘要求，返回结构化字段（含原文证据）。"""
        if self.is_mock:
            candidates = self._rule_based_candidates(raw_text)
            extracted_by = "mock"
        else:
            try:
                candidates = self._model_based_candidates(raw_text)
                extracted_by = f"{self.mode}:{self.config.get('model', 'unknown')}"
            except ModelError:
                if not self.fallback_to_mock:
                    raise
                candidates = self._rule_based_candidates(raw_text)
                extracted_by = "mock(fallback)"
        result = self._normalize(raw_text, candidates, job_id, extracted_by)
        return result

    def _rule_based_candidates(self, text: str) -> list[dict]:
        """模拟模式：逐句扫描，按语境判断 required/bonus，返回候选命中。"""
        candidates: list[dict] = []
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        for sentence in sentences:
            is_bonus_ctx = any(marker in sentence for marker in _BONUS_MARKERS)
            for entry in self.matchers:
                for pat in entry["patterns"]:
                    if pat.search(sentence):
                        candidates.append({
                            "alias_hit": pat.pattern,
                            "requirement": "bonus" if is_bonus_ctx else "required",
                            "quote": sentence,
                        })
                        break  # 该技能在本句命中一次即可
        return candidates

    def _model_based_candidates(self, text: str) -> list[dict]:
        """真实模型模式：让模型输出候选命中与证据，程序再归一。"""
        system = (
            "你是招聘信息分析助手。只分析用户提供的招聘文本，输出 JSON，不要输出多余内容。"
            "对每个识别到的技能/要求给出：skill_name（原文中的名称或常见别名）、"
            "requirement（required 硬性要求 或 bonus 加分项）、quote（支撑该判断的原文短句）。"
            "出现在‘加分项/优先/为佳’语境中的判为 bonus。输出格式："
            '{"candidates":[{"skill_name":"...","requirement":"required","quote":"..."}]}'
        )
        message = self._chat_raw([
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ])
        parsed = self._parse_json_block(message)
        spec = {"candidates": {"type": "list", "required": True,
                               "item": {"type": "dict"}}}
        validate(parsed, spec)
        out = []
        for c in parsed["candidates"]:
            validate(c, {
                "skill_name": {"type": "str", "required": True},
                "requirement": {"type": "str", "required": True, "enum": ["required", "bonus"]},
                "quote": {"type": "str", "required": True},
            })
            out.append({"alias_hit": c["skill_name"], "requirement": c["requirement"], "quote": c["quote"]})
        return out

    # ---------- 程序归一（模型/模拟共用） ----------
    def _normalize(self, raw_text: str, candidates: list[dict], job_id: str, extracted_by: str) -> dict:
        """别名归一 → 单条招聘去重 → required 优先；并提取学历与经验。"""
        index = {s["skill"]["canonical_id"]: s for s in self.matchers}
        merged: dict[str, dict] = {}
        for cand in candidates:
            canonical_id = self._resolve_canonical(cand["alias_hit"])
            if not canonical_id:
                continue
            skill = index[canonical_id]["skill"]
            item = merged.setdefault(canonical_id, {
                "skill_id": canonical_id,
                "name": skill["name"],
                "category": skill["category"],
                "requirement": cand["requirement"],
                "quotes": [],
            })
            # 同一招聘内：硬性要求优先于加分
            if cand["requirement"] == "required":
                item["requirement"] = "required"
            if cand["quote"] not in item["quotes"] and len(item["quotes"]) < 2:
                item["quotes"].append(cand["quote"])

        degree = self._extract_degree(raw_text)
        experience = self._extract_experience(raw_text)
        return {
            "job_id": job_id,
            "extracted_by": extracted_by,
            "skills": sorted(merged.values(), key=lambda x: (x["category"], x["skill_id"])),
            "degree": degree,
            "experience": experience,
        }

    def _resolve_canonical(self, hit: str) -> str | None:
        """把任意命中（别名/标准名/模型给出的名称）解析为 canonical_id。"""
        hit_norm = hit.strip().lower()
        for entry in self.matchers:
            skill = entry["skill"]
            if hit_norm == skill["canonical_id"] or hit_norm == skill["name"].lower():
                return skill["canonical_id"]
            for alias in skill["aliases"]:
                if hit_norm == alias.lower():
                    return skill["canonical_id"]
        # 宽松匹配：作为子串再试一次（处理模型输出的变体）
        for entry in self.matchers:
            skill = entry["skill"]
            names = [skill["canonical_id"], skill["name"]] + skill["aliases"]
            if any(n.lower() in hit_norm or hit_norm in n.lower() for n in names):
                return skill["canonical_id"]
        return None

    def _extract_degree(self, text: str) -> dict:
        for kw in _DEGREE_MASTER:
            if kw in text:
                return {"level": "master_or_above", "quote": kw}
        for kw in _DEGREE_BACHELOR:
            if kw:
                return {"level": "bachelor_or_above", "quote": kw}
        return {"level": "unknown", "quote": ""}

    def _extract_experience(self, text: str) -> dict:
        if "应届" in text:
            return {"type": "campus", "quote": "应届"}
        m = re.search(r"(\d+)\s*年.*?经验", text)
        if m:
            return {"type": "experienced", "quote": m.group(0)}
        return {"type": "campus", "quote": "校招岗位（未明确年限）"}

    # ---------- Agent 工具选择 ----------
    def select_tool(self, messages: list[dict], tools: list[dict]) -> dict:
        """让模型选择工具，返回 {tool_name, arguments} 或 {final_answer}。"""
        if self.is_mock:
            raise ModelError("模拟模式不调用模型选工具，应由 Agent 规则路由处理")
        resp = self._chat_raw(messages, tools=tools)
        # 正常情况下 _chat_raw 已解析 tool_calls；这里 resp 为 message 字典
        if resp.get("tool_calls"):
            call = resp["tool_calls"][0]
            fn = call.get("function", {})
            try:
                arguments = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                raise ModelError("模型返回的工具参数不是合法 JSON")
            return {"tool_name": fn.get("name", ""), "arguments": arguments}
        return {"final_answer": resp.get("content", "")}

    # ---------- 底层 HTTP（OpenAI 兼容） ----------
    def _chat_raw(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        url = self.config.get("base_url", "").rstrip("/")
        if not url:
            raise ModelError("未配置 base_url（服务地址）")
        body: dict[str, Any] = {
            "model": self.config.get("model", ""),
            "messages": messages,
            "temperature": 0.1,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        api_key = self.config.get("api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
            raise ModelError(f"HTTP {e.code}：{detail}") from e
        except urllib.error.URLError as e:
            raise ModelError(f"无法连接模型服务 {url}：{e.reason}") from e
        except (TimeoutError, json.JSONDecodeError) as e:
            raise ModelError(f"模型响应异常：{e}") from e
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise ModelError(f"模型返回缺少 choices[0].message：{str(data)[:200]}") from e

    @staticmethod
    def _parse_json_block(text: str) -> dict:
        """剥离模型可能输出的 ```json 代码块并解析 JSON。"""
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ModelError(f"模型未返回合法 JSON：{text[:200]}") from e
