# -*- coding: utf-8 -*-
"""岗位需求反推成长规划 Agent —— 本地应用入口（零第三方依赖）。

启动：python app.py，然后浏览器访问 http://127.0.0.1:8000
或双击 start.bat。仅使用 Python 标准库，单用户本地运行。
"""
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.agent import CareerAgent
from core.model_adapter import ModelAdapter, ModelError
from core.schema import PROFILE_SPEC, ValidationError, validate
from core.storage import StateStore, load_json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_DIR = os.path.join(BASE_DIR, "state")
WEB_DIR = os.path.join(BASE_DIR, "web")
PORT = int(os.environ.get("CAREER_PORT", "8000"))
# 绑定地址：默认仅本机可访问（安全）。设为 0.0.0.0 可让同一局域网内的
# 其他设备访问（答辩演示场景），通过环境变量 CAREER_HOST 控制。
HOST = os.environ.get("CAREER_HOST", "127.0.0.1")

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def load_config() -> dict:
    cfg_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(cfg_path):
        return load_json(cfg_path)
    return {"mode": "mock", "model": "mock-rules", "base_url": "",
            "api_key": "", "timeout_seconds": 60, "fallback_to_mock": False}


def build_agent() -> CareerAgent:
    config = load_config()
    taxonomy_path = os.path.join(DATA_DIR, "skill_taxonomy.json")
    adapter = ModelAdapter(config, taxonomy_path)
    data_docs = {
        "jobs": load_json(os.path.join(DATA_DIR, "jobs.json")),
        "courses": load_json(os.path.join(DATA_DIR, "courses.json")),
        "activities": load_json(os.path.join(DATA_DIR, "activities.json")),
    }
    store = StateStore(STATE_DIR)
    return CareerAgent(store, adapter, data_docs)


AGENT = build_agent()


class Handler(BaseHTTPRequestHandler):
    server_version = "CareerAgent/1.0"

    def log_message(self, fmt, *args):  # 精简控制台日志
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- 响应工具 ----------
    def _send_json(self, obj: dict, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel_path: str):
        full = os.path.abspath(os.path.join(WEB_DIR, rel_path))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self._send_json({"ok": False, "error": "资源不存在"}, 404)
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", _MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send_static("index.html")
        if path.startswith("/web/"):
            return self._send_static(path[len("/web/"):])
        if path == "/api/state":
            return self._send_json(AGENT.run_tool("get_state", {}, "page"))
        if path == "/api/records":
            return self._send_json({"ok": True, "records": AGENT.get_records()})
        if path == "/api/model_status":
            return self._send_json({"ok": True, "status": AGENT.adapter.status()})
        if path == "/api/families":
            custom = AGENT.store.load_custom_families().get("families", [])
            return self._send_json({"ok": True, "families": custom})
        if path == "/api/plan/latest":
            versions = AGENT.store.load_plans().get("versions", [])
            if not versions:
                return self._send_json({"ok": False, "message": "尚无计划版本"})
            return self._send_json({"ok": True, "plan": versions[-1]})
        if path == "/api/data":
            return self._send_json({
                "ok": True,
                "jobs": [{"job_id": j["job_id"], "family": j["family"], "title": j["title"],
                          "company": j["company"], "source_url": j["source_url"],
                          "source_name": j["source_name"], "salary": j["salary"],
                          "location": j["location"]}
                         for j in AGENT.tools.jobs_doc["jobs"]],
                "courses": AGENT.tools.courses_doc["courses"],
                "activities": AGENT.tools.activities_doc["activities"],
                "taxonomy": AGENT.adapter.taxonomy["skills"],
            })
        return self._send_json({"ok": False, "error": f"未知路径 {path}"}, 404)

    # ---------- POST ----------
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (json.JSONDecodeError, ValueError):
            return self._send_json({"ok": False, "error": "请求体不是合法 JSON"}, 400)

        if path == "/api/profile":
            return self._save_profile(payload)
        if path == "/api/chat":
            msg = str(payload.get("message", "")).strip()
            if not msg:
                return self._send_json({"ok": False, "error": "message 不能为空"}, 400)
            return self._send_json(AGENT.chat(msg))
        if path.startswith("/api/tool/"):
            tool_name = path[len("/api/tool/"):]
            return self._send_json(AGENT.run_tool(tool_name, payload, "page"))
        if path == "/api/reset":
            for name in ("profile.json", "job_analysis.json", "plans.json",
                         "tasks.json", "agent_logs.json", "custom_jobs.json",
                         "custom_families.json"):
                p = os.path.join(STATE_DIR, name)
                if os.path.isfile(p):
                    os.remove(p)
            AGENT.logs = {"records": []}
            return self._send_json({"ok": True, "message": "已重置本地状态"})
        return self._send_json({"ok": False, "error": f"未知路径 {path}"}, 404)

    def _save_profile(self, payload: dict):
        payload.setdefault("mastered_skills", [])
        payload.setdefault("pending_skills", [])
        try:
            validate(payload, PROFILE_SPEC)
        except ValidationError as e:
            return self._send_json({"ok": False, "error": e.errors}, 400)
        AGENT.store.save_profile(payload)
        AGENT.logs["records"].append({
            "seq": len(AGENT.logs["records"]) + 1, "trigger": "page",
            "tool_name": "save_profile", "arguments": payload, "ok": True,
            "at": _now(), "model_mode": AGENT.adapter.status()["mode"]})
        AGENT.store.save_logs(AGENT.logs)
        return self._send_json({"ok": True, "message": "画像已保存，重启后可恢复"})


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print("=" * 60)
    print("岗位需求反推成长规划 Agent 已启动")
    print(f"模型模式：{AGENT.adapter.status()['mode']}（模拟模式无需密钥即可完整演示）")
    print(f"本机访问：{url}")
    if HOST in ("0.0.0.0", "::"):
        print("已开启局域网访问：同一 WiFi 下其他设备可用下方地址访问")
        _print_lan_urls(PORT)
    print("按 Ctrl+C 退出")
    print("=" * 60)
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出...")
        server.shutdown()


def _print_lan_urls(port: int) -> None:
    """打印本机局域网 IPv4 地址，供同一网络下的设备访问。"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except OSError:
            ip = ""
        finally:
            s.close()
        if ip:
            print(f"  局域网地址：http://{ip}:{port}/")
        else:
            print("  （未能自动探测局域网 IP，可用 ipconfig 查看 IPv4 地址）")
    except Exception:
        pass


if __name__ == "__main__":
    main()
