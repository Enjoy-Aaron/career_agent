# -*- coding: utf-8 -*-
"""打印两个岗位族的完整技能计数，用于核对核心/长尾划分。

用法：python scripts/show_aggregate.py
"""
import json
import urllib.request

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/tool/get_aggregate",
    data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req) as r:
    agg = json.loads(r.read())["aggregate"]

for f in agg["families"]:
    print("===", f["family"], "job_count=", f["job_count"],
          "master_jobs=", f["master_degree_jobs"])
    for s in f["skills"]:
        print(f"  {s['skill_id']:<22}{s['name']:<20}硬{s['required_count']} "
              f"加{s['bonus_count']} cat={s['category']}")
