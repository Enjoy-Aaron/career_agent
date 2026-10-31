/* 岗位需求反推成长规划 Agent —— 前端逻辑（原生 JS，零依赖） */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const CATEGORY_NAMES = {
  language: "编程语言", backend_framework: "后端框架", data_storage: "数据与中间件",
  cs_foundation: "计算机基础", devops: "工程与运维", ai: "人工智能", soft_skill: "通用能力",
};

let DATA = null;   // /api/data
let STATE = null;  // /api/state

// ---------- 工具 ----------
async function api(path, body) {
  const opt = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const resp = await fetch(path, opt);
  return resp.json();
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) {
  return typeof u === "string" && /^https?:\/\//i.test(u) ? u : "";
}
function flash(el, ok, text) {
  el.textContent = text;
  el.className = "inline-msg " + (ok ? "msg-ok" : "msg-err");
}
function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- 标签切换 ----------
$$("#tabs .tab").forEach((t) => t.addEventListener("click", () => {
  $$("#tabs .tab").forEach((x) => x.classList.remove("active"));
  $$(".panel").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  $("#panel-" + t.dataset.tab).classList.add("active");
  if (t.dataset.tab === "adjust") renderCompletionList();
  if (t.dataset.tab === "chat") loadRecords();
}));

// ---------- 初始化 ----------
async function init() {
  DATA = await api("/api/data");
  STATE = await api("/api/state");
  renderModelBadge();
  renderSkillPickers();
  renderJobList();
  fillProfileForm();
  await refreshFamilyOptions();
  if (STATE && STATE.latest_plan) {
    const latest = await api("/api/plan/latest");
    if (latest.ok) renderPlan(latest.plan);
  }
}
function renderModelBadge() {
  const st = STATE.model_status || { mode: "mock" };
  const badge = $("#model-badge");
  const modelName = st.model || "";
  let label = st.mode === "mock" ? "模拟模式（无需密钥）"
    : st.mode === "local" ? "本地模型：" + (modelName || "未配置")
    : "云端模型：" + (modelName || "未配置");
  badge.textContent = label;
  badge.title = "当前模型模式：" + st.mode + (modelName ? "，模型：" + modelName : "");
  badge.className = "badge badge-" + st.mode;
}

// ---------- 技能选择器 ----------
function renderSkillPickers() {
  const groups = {};
  DATA.taxonomy.forEach((s) => (groups[s.category] ||= []).push(s));
  const build = (elId, checked) => {
    const el = $("#" + elId);
    el.innerHTML = "";
    Object.entries(groups).forEach(([cat, skills]) => {
      const title = document.createElement("div");
      title.className = "skill-group-title";
      title.textContent = CATEGORY_NAMES[cat];
      el.appendChild(title);
      skills.forEach((s) => {
        const lab = document.createElement("label");
        lab.innerHTML = `<input type="checkbox" value="${esc(s.canonical_id)}" ${checked.includes(s.canonical_id) ? "checked" : ""}> ${esc(s.name)}`;
        el.appendChild(lab);
      });
    });
  };
  const mastered = STATE.profile ? STATE.profile.mastered_skills : ["python", "git", "data_structure"];
  const pending = STATE.profile ? STATE.profile.pending_skills : [];
  build("skill-picker", mastered);
  build("pending-picker", pending);
}
function pickValues(elId) {
  return $$(`#${elId} input:checked`).map((i) => i.value);
}

// ---------- 画像 ----------
function fillProfileForm() {
  const p = STATE.profile;
  if (!p) return;
  $("#f-major").value = p.major;
  $("#f-semester").value = p.semester;
  $("#f-family").value = p.target_family;
  $("#f-hours").value = p.weekly_hours;
  $("#f-path").value = p.path;
}
$("#btn-save-profile").addEventListener("click", async () => {
  const profile = {
    major: $("#f-major").value.trim(),
    semester: Number($("#f-semester").value),
    target_family: $("#f-family").value,
    weekly_hours: Number($("#f-hours").value),
    path: $("#f-path").value,
    mastered_skills: pickValues("skill-picker"),
    pending_skills: pickValues("pending-picker"),
  };
  const r = await api("/api/profile", profile);
  flash($("#profile-msg"), r.ok, r.ok ? "画像已保存" : JSON.stringify(r.error));
  if (r.ok) STATE = await api("/api/state");
});

// ---------- 招聘列表 ----------
function renderJobList() {
  const famLabel = { backend: "后端", ai: "AI算法" };
  $("#job-list").innerHTML = DATA.jobs.map((j) => `
    <div class="job-item">
      <div>
        <strong>${esc(j.title)}｜${esc(j.company)}</strong>
        <div class="meta">${esc(j.location)} ${esc(j.salary)} · ${esc(j.source_name)} · 获取于 2026-10-30</div>
      </div>
      <div style="text-align:right">
        <span class="fam-tag ${j.family === "backend" ? "fam-backend" : j.family === "ai" ? "fam-ai" : "fam-custom"}">${famLabel[j.family] || esc(j.family)}</span>
        ${safeUrl(j.source_url) ? `<div style="margin-top:5px"><a href="${esc(j.source_url)}" target="_blank" rel="noopener">查看原文 ↗</a></div>` : ""}
      </div>
    </div>`).join("");
}
$("#btn-paste").addEventListener("click", async () => {
  const text = $("#paste-text").value.trim();
  if (!text) return flash($("#analyze-msg"), false, "请先粘贴招聘文本");
  const r = await api("/api/tool/add_custom_job", {
    raw_text: text, family: $("#paste-family").value,
    company: $("#paste-company").value.trim(), source_url: $("#paste-url").value.trim(),
  });
  flash($("#analyze-msg"), r.ok, r.ok ? `已登记 ${r.job_id}` : JSON.stringify(r.error));
  if (r.ok) { $("#paste-text").value = ""; DATA = await api("/api/data"); renderJobList(); }
});

// 登记自定义岗位族
$("#btn-add-family").addEventListener("click", async () => {
  const fid = $("#fam-id").value.trim();
  const label = $("#fam-label").value.trim();
  if (!fid || !label) return flash($("#family-msg"), false, "请填写族标识与显示名");
  const r = await api("/api/tool/add_custom_family", { family: fid, label });
  flash($("#family-msg"), r.ok, r.ok ? r.message : JSON.stringify(r.error));
  if (r.ok) { $("#fam-id").value = ""; $("#fam-label").value = ""; await refreshFamilyOptions(); }
});

// 批量导入招聘
$("#btn-import").addEventListener("click", async () => {
  const text = $("#import-text").value.trim();
  if (!text) return flash($("#import-msg"), false, "请粘贴 JSON 数组");
  let items;
  try { items = JSON.parse(text); } catch (e) { return flash($("#import-msg"), false, "JSON 格式错误：" + e.message); }
  if (!Array.isArray(items)) return flash($("#import-msg"), false, "需为 JSON 数组");
  const r = await api("/api/tool/import_jobs", { items });
  flash($("#import-msg"), r.ok, r.ok ? r.message : JSON.stringify(r.error));
  if (r.ok) { $("#import-text").value = ""; DATA = await api("/api/data"); renderJobList(); }
});

// URL 抓取招聘
$("#btn-fetch").addEventListener("click", async () => {
  const url = $("#fetch-url").value.trim();
  if (!url) return flash($("#fetch-msg"), false, "请输入招聘页链接");
  flash($("#fetch-msg"), true, "抓取中…");
  const r = await api("/api/tool/fetch_job_from_url", { url, family: $("#fetch-family").value });
  flash($("#fetch-msg"), r.ok, r.ok ? r.message : r.message || JSON.stringify(r.error));
  if (r.ok) { $("#fetch-url").value = ""; DATA = await api("/api/data"); renderJobList(); }
});

// 刷新各下拉框的自定义族选项
async function refreshFamilyOptions() {
  const fams = await api("/api/families");
  if (!fams.ok) return;
  const customOpts = fams.families.map((f) =>
    `<option value="${esc(f.family)}">${esc(f.label)}</option>`).join("");
  const preset = {
    "paste-family": [["backend", "后端开发"], ["ai", "AI 算法"]],
    "f-family": [["backend", "后端开发工程师（Java 方向）"], ["ai", "AI 算法工程师"]],
    "adj-family": [["", "不改变"], ["backend", "后端开发"], ["ai", "AI 算法"]],
  };
  Object.keys(preset).forEach((selId) => {
    const sel = $("#" + selId);
    const cur = sel.value;
    const presetHtml = preset[selId].map(([v, t]) =>
      `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(t)}</option>`).join("");
    sel.innerHTML = presetHtml + customOpts.replace(/<option value="([^"]+)"/g, (m, v) =>
      `<option value="${v}" ${v === cur ? "selected" : ""}`);
  });
}

$("#btn-analyze").addEventListener("click", async () => {
  flash($("#analyze-msg"), true, "分析中…");
  const r = await api("/api/tool/analyze_jobs", { family: "all" });
  if (!r.ok) return flash($("#analyze-msg"), false, JSON.stringify(r.error));
  flash($("#analyze-msg"), true, `已分析 ${r.analyzed_jobs} 条招聘`);
  const agg = await api("/api/tool/get_aggregate", {});
  renderAnalysis(agg.aggregate);
});

function renderAnalysis(agg) {
  $("#analysis-card").classList.remove("hidden");
  $("#analysis-result").innerHTML = agg.families.map((f) => `
    <div class="fam-block">
      <h3>${f.family === "backend" ? "后端开发" : "AI 算法"}（${f.job_count} 条招聘）</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>技能</th><th>类别</th><th>硬性(条)</th><th>加分(条)</th><th>提及频率</th><th>证据</th></tr></thead>
        <tbody>${f.skills.map((s, i) => `
          <tr>
            <td>${esc(s.name)}</td>
            <td>${CATEGORY_NAMES[s.category]}</td>
            <td class="req-pill">${s.required_count}</td>
            <td class="bonus-pill">${s.bonus_count}</td>
            <td>${(s.mention_freq * 100).toFixed(0)}%</td>
            <td><span class="evidence-toggle" data-idx="${f.family}-${i}">展开 ${s.evidence.length} 条</span></td>
          </tr>`).join("")}
        </tbody></table></div>
      ${f.skills.map((s, i) => `
        <div class="evidence-box hidden" id="ev-${f.family}-${i}">
          ${s.evidence.map((e) => `
            <p><strong>${esc(e.company)}（${e.requirement === "required" ? "硬性" : "加分"}）</strong><br>
            “${esc(e.quotes.join(" "))}”<br>
            ${safeUrl(e.source_url) ? `<a href="${esc(e.source_url)}" target="_blank" rel="noopener">${esc(e.source_url)}</a>` : ""}</p>`).join("")}
        </div>`).join("")}
    </div>`).join("");
  $$(".evidence-toggle").forEach((t) => t.addEventListener("click", () => {
    $("#ev-" + t.dataset.idx).classList.toggle("hidden");
  }));
  renderSkillChart(agg);
  renderCategoryDonut(agg);
}

// ============ 可视化：技能频次对比图（纯 SVG 双色横向条形） ============
function renderSkillChart(agg) {
  $("#chart-card").classList.remove("hidden");
  const fam = agg.families[0]; // 展示第一个岗位族，多族时可并排
  const skills = fam.skills.slice(0, 12).filter((s) => s.required_count + s.bonus_count > 0);
  const maxVal = Math.max(1, ...skills.map((s) => s.required_count + s.bonus_count));
  const W = 720, rowH = 34, barMax = 360, padL = 150, padR = 20, top = 8;
  const H = top + skills.length * rowH + 24;
  const famName = fam.family === "backend" ? "后端开发" : "AI 算法";
  let bars = "";
  skills.forEach((s, i) => {
    const y = top + i * rowH;
    const reqW = (s.required_count / maxVal) * barMax;
    const bonW = (s.bonus_count / maxVal) * barMax;
    const x0 = padL;
    bars += `
      <text x="${padL - 8}" y="${y + 19}" text-anchor="end" class="c-label">${esc(s.name)}</text>
      <rect x="${x0}" y="${y}" width="${reqW}" height="18" rx="4" class="bar-req"></rect>
      ${s.required_count ? `<text x="${x0 + reqW / 2}" y="${y + 13}" text-anchor="middle" class="c-count">${s.required_count}</text>` : ""}
      <rect x="${x0 + reqW + 2}" y="${y}" width="${bonW}" height="18" rx="4" class="bar-bonus"></rect>
      ${s.bonus_count ? `<text x="${x0 + reqW + 2 + bonW / 2}" y="${y + 13}" text-anchor="middle" class="c-count">${s.bonus_count}</text>` : ""}
      <text x="${x0 + barMax + 12}" y="${y + 13}" class="c-freq">${Math.round(s.mention_freq * 100)}%</text>`;
  });
  $("#skill-chart").innerHTML = `
    <div class="chart-caption">${famName} · ${fam.job_count} 条招聘 · 按硬性出现次数排序</div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img">
      ${bars}
    </svg>`;
}

// ============ 可视化：能力差距雷达图 ============
function renderGapChart(gap, mastered) {
  if (!gap || !gap.job_count) return;
  const masterSet = new Set(mastered || []);
  const req = gap.required_gaps || [];
  const bonus = gap.bonus_gaps || [];
  // 维度：硬性缺口（按 required_count 排序）+ 目标族内已掌握技能（按岗位提及排序）
  // 这样既能看出"还缺什么"，也能对比"已掌握了哪些岗位要求的能力"
  const masteredInTarget = (gap.mastered_in_target || [])
    .map((sid) => {
      const s = [...req, ...bonus].find((x) => x.skill_id === sid);
      return s || { skill_id: sid, name: sid, category: "soft_skill", required_count: 0, bonus_count: 0 };
    })
    .sort((a, b) => (b.required_count + b.bonus_count) - (a.required_count + a.bonus_count));
  const reqSorted = req.slice().sort((a, b) => b.required_count - a.required_count);
  // 合并去重：优先硬性缺口，再补已掌握（最多 8 维，避免雷达图过密）
  const seen = new Set();
  const dimsArr = [];
  for (const s of [...reqSorted, ...masteredInTarget]) {
    if (seen.has(s.skill_id) || dimsArr.length >= 8) continue;
    seen.add(s.skill_id);
    dimsArr.push(s);
  }
  if (!dimsArr.length) return;
  const n = dimsArr.length;
  const total = gap.job_count || 1;
  const cx = 220, cy = 200, R = 140;
  const angle = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pt = (i, r) => [cx + Math.cos(angle(i)) * r, cy + Math.sin(angle(i)) * r];
  // 岗位要求强度 = required_count / total（已掌握的技能按其在岗位中的要求强度展示）
  const reqVal = dimsArr.map((s) => Math.min(1, (s.required_count || 0) / total));
  const myVal = dimsArr.map((s) => (masterSet.has(s.skill_id) ? 1 : 0));
  const poly = (vals) => vals.map((v, i) => pt(i, Math.max(0.02, v) * R).join(",")).join(" ");
  // 网格环
  let grid = "";
  for (let g = 1; g <= 4; g++) {
    const r = (R * g) / 4;
    grid += `<polygon points="${dimsArr.map((_, i) => pt(i, r).join(",")).join(" ")}" class="radar-grid"></polygon>`;
  }
  let axes = "";
  dimsArr.forEach((_, i) => {
    const [x, y] = pt(i, R);
    axes += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" class="radar-axis"></line>`;
  });
  let labs = "";
  dimsArr.forEach((s, i) => {
    const [x, y] = pt(i, R + 26);
    const anchor = x < cx - 6 ? "end" : x > cx + 6 ? "start" : "middle";
    labs += `<text x="${x}" y="${y}" text-anchor="${anchor}" class="radar-label">${esc(s.name)}</text>`;
  });
  const dots = dimsArr.map((s, i) => {
    const [x, y] = pt(i, myVal[i] * R);
    return `<circle cx="${x}" cy="${y}" r="3.5" class="radar-dot"></circle>`;
  }).join("");
  $("#gap-chart-card").classList.remove("hidden");
  $("#gap-chart").innerHTML = `
    <svg viewBox="0 0 440 400" width="100%" style="max-width:440px" role="img">
      ${grid}${axes}
      <polygon points="${poly(reqVal)}" class="radar-req"></polygon>
      <polygon points="${poly(myVal)}" class="radar-mine"></polygon>
      ${dots}${labs}
    </svg>
    <div class="radar-legend">
      <span><i class="dot dot-req"></i>岗位核心要求强度</span>
      <span><i class="dot dot-mine"></i>你已掌握</span>
    </div>`;
}

// ============ 可视化：岗位能力结构环形图（技能类别占比） ============
function renderCategoryDonut(agg) {
  if (!agg || !agg.families || !agg.families.length) return;
  const fam = agg.families[0];
  const skills = fam.skills || [];
  if (!skills.length) return;
  const catCount = {};
  const catColors = {
    language: "#146356", backend_framework: "#2f6f8f", data_storage: "#cf8427",
    cs_foundation: "#b14a3c", devops: "#7a5c9e", ai: "#d97706", soft_skill: "#64748b",
  };
  skills.forEach((s) => {
    catCount[s.category] = (catCount[s.category] || 0) + (s.required_count + s.bonus_count);
  });
  const entries = Object.entries(catCount).filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1;
  const cx = 140, cy = 140, r = 100, stroke = 40;
  const C = 2 * Math.PI * (r - stroke / 2);
  let offset = 0;
  let segs = "";
  entries.forEach(([cat, v]) => {
    const frac = v / total;
    const len = frac * C;
    const dash = `${len} ${C - len}`;
    segs += `<circle cx="${cx}" cy="${cy}" r="${r - stroke / 2}" fill="none"
      stroke="${catColors[cat] || "#999"}" stroke-width="${stroke}"
      stroke-dasharray="${dash}" stroke-dashoffset="${-offset}"
      transform="rotate(-90 ${cx} ${cy})">
      <title>${esc(CATEGORY_NAMES[cat] || cat)}：${v} 次提及</title></circle>`;
    offset += len;
  });
  // 中心文字
  const center = `<text x="${cx}" y="${cy - 8}" text-anchor="middle" class="donut-total">${total}</text>
    <text x="${cx}" y="${cy + 14}" text-anchor="middle" class="donut-sub">次技能提及</text>`;
  // 图例
  const legend = entries.map(([cat, v]) => `
    <span><i class="dot" style="background:${catColors[cat] || "#999"}"></i>
      ${esc(CATEGORY_NAMES[cat] || cat)} · ${v}（${Math.round(v / total * 100)}%）</span>`).join("");
  $("#category-card").classList.remove("hidden");
  $("#category-chart").innerHTML = `
    <svg viewBox="0 0 280 280" width="100%" style="max-width:280px" role="img">${segs}${center}</svg>
    <div class="donut-legend">${legend}</div>`;
}

// ============ 可视化：缺口优先级矩阵（先学什么） ============
function renderPriorityMatrix(gap) {
  if (!gap || !gap.job_count) return;
  const req = gap.required_gaps || [];
  const bonus = gap.bonus_gaps || [];
  const all = [...req, ...bonus];
  if (!all.length) return;
  const total = gap.job_count || 1;
  // 横轴：提及频次(0~1)；纵轴：硬性占比(required/mention, 0~1)
  const W = 760, H = 380, padL = 56, padR = 20, padT = 20, padB = 44;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const pts = all.map((s) => {
    const mention = s.required_count + s.bonus_count;
    const freq = mention / total;
    const hardRatio = mention ? s.required_count / mention : 0;
    return { s, freq, hardRatio, mention };
  });
  const x = (freq) => padL + freq * plotW;
  const y = (hr) => padT + (1 - hr) * plotH;
  // 网格 + 轴刻度
  let grid = "";
  for (let i = 0; i <= 4; i++) {
    const gx = padL + (i / 4) * plotW;
    const gy = padT + (i / 4) * plotH;
    grid += `<line x1="${gx}" y1="${padT}" x2="${gx}" y2="${padT + plotH}" class="radar-axis"></line>`;
    grid += `<line x1="${padL}" y1="${gy}" x2="${padL + plotW}" y2="${gy}" class="radar-axis"></line>`;
    grid += `<text x="${gx}" y="${H - padB + 18}" text-anchor="middle" class="axis-tick">${(i * 25)}%</text>`;
    grid += `<text x="${padL - 8}" y="${gy + 4}" text-anchor="end" class="axis-tick">${(100 - i * 25)}%</text>`;
  }
  // 象限辅助线（中点）
  grid += `<line x1="${padL + plotW / 2}" y1="${padT}" x2="${padL + plotW / 2}" y2="${padT + plotH}" class="quad-line"></line>`;
  grid += `<line x1="${padL}" y1="${padT + plotH / 2}" x2="${padL + plotW}" y2="${padT + plotH / 2}" class="quad-line"></line>`;
  // 象限标注
  const qLabels = [
    { x: padL + plotW * 0.75, y: padT + 18, t: "核心必修（优先补齐）", cls: "q-hot" },
    { x: padL + plotW * 0.25, y: padT + 18, t: "常见但非硬性", cls: "q-warm" },
    { x: padL + plotW * 0.25, y: padT + plotH - 8, t: "长尾/可选", cls: "q-cool" },
    { x: padL + plotW * 0.75, y: padT + plotH - 8, t: "关键但少见", cls: "q-niche" },
  ];
  const qs = qLabels.map((q) => `<text x="${q.x}" y="${q.y}" text-anchor="middle" class="${q.cls}">${q.t}</text>`).join("");
  // 气泡：半径随 mention 频次
  const bubbles = pts.map((p) => {
    const r = 6 + Math.min(16, p.mention * 6);
    const isGap = !(gap.mastered_in_target || []).includes(p.s.skill_id) && p.s.required_count > 0;
    const fill = isGap ? "var(--red)" : "var(--green)";
    const cx = x(p.freq), cy = y(p.hardRatio);
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" opacity="0.55" stroke="${fill}" stroke-width="1">
        <title>${esc(p.s.name)}：${p.mention} 条提及，硬性 ${p.s.required_count} / 加分 ${p.s.bonus_count}</title></circle>
      <text x="${cx}" y="${cy + 3}" text-anchor="middle" class="bubble-txt">${esc(p.s.skill_id.length > 8 ? p.s.skill_id.slice(0, 7) + "…" : p.s.skill_id)}</text>`;
  }).join("");
  $("#priority-card").classList.remove("hidden");
  $("#priority-chart").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:${W}px" role="img">
      ${grid}${qs}${bubbles}
      <text x="${padL}" y="${H - padB + 36}" class="axis-label">← 提及频率低　　　　提及频率高 →</text>
      <text x="14" y="${padT + plotH / 2}" transform="rotate(-90 14 ${padT + plotH / 2})" text-anchor="middle" class="axis-label">硬性占比</text>
    </svg>
    <div class="radar-legend">
      <span><i class="dot" style="background:var(--red)"></i>硬性缺口（待补）</span>
      <span><i class="dot" style="background:var(--green)"></i>已掌握</span>
      <span class="hint">气泡越大 = 被越多招聘提及</span>
    </div>`;
}

// ============ 可视化：学期工作量堆叠图 ============
function renderWorkloadChart(plan) {
  if (!plan || !plan.semester_plans || !plan.semester_plans.length) return;
  const sems = plan.semester_plans;
  const W = 760, padL = 56, padR = 20, padT = 20, padB = 44;
  const plotW = W - padL - padR, plotH = 240;
  const colGap = 10;
  const colW = Math.floor((plotW - colGap * (sems.length - 1)) / sems.length);
  const maxBudget = Math.max(1, ...sems.map((s) => s.budget_hours));
  const y = (h) => padT + plotH - (h / maxBudget) * plotH;
  let cols = "", grid = "";
  // 横向网格（每 25% 预算）
  for (let i = 0; i <= 4; i++) {
    const gy = padT + (i / 4) * plotH;
    const val = Math.round(maxBudget * (1 - i / 4));
    grid += `<line x1="${padL}" y1="${gy}" x2="${padL + plotW}" y2="${gy}" class="radar-axis"></line>
      <text x="${padL - 8}" y="${gy + 4}" text-anchor="end" class="axis-tick">${val}h</text>`;
  }
  sems.forEach((sp, i) => {
    const x = padL + i * (colW + colGap);
    const fixed = sp.fixed.reduce((s, it) => s + it.workload_hours, 0);
    const reg = sp.scheduled.filter((it) => it.status !== "recurring").reduce((s, it) => s + it.workload_hours, 0);
    const rec = sp.scheduled.filter((it) => it.status === "recurring").reduce((s, it) => s + it.workload_hours, 0);
    const yF = y(fixed), yR = y(fixed + reg), yRec = y(fixed + reg + rec);
    const yTop = y(fixed + reg + rec);
    // 三段堆叠：固定块(amber) / 常规(green) / 持续(teal)
    const segs = `
      <rect x="${x}" y="${yTop}" width="${colW}" height="${yF - yTop}" fill="#cf8427" rx="3"><title>固定块 ${fixed}h</title></rect>
      <rect x="${x}" y="${yR}" width="${colW}" height="${yRec - yR}" fill="#146356" rx="3"><title>常规 ${reg}h</title></rect>
      <rect x="${x}" y="${yF}" width="${colW}" height="${yR - yF}" fill="#2f9e8f" rx="3"><title>持续投入 ${rec}h</title></rect>`;
    // 预算虚线标记
    const yB = y(sp.budget_hours);
    const marker = `<line x1="${x}" y1="${yB}" x2="${x + colW}" y2="${yB}" class="budget-line"></line>`;
    cols += `
      ${marker}${segs}
      <text x="${x + colW / 2}" y="${padT + plotH + 16}" text-anchor="middle" class="axis-tick">第${sp.semester}学期</text>
      <text x="${x + colW / 2}" y="${yTop - 5}" text-anchor="middle" class="stack-total">${Math.round(fixed + reg + rec)}h</text>`;
  });
  $("#workload-card").classList.remove("hidden");
  $("#workload-chart").innerHTML = `
    <svg viewBox="0 0 ${W} ${padT + plotH + padB}" width="100%" style="min-width:${W}px" role="img">
      ${grid}${cols}
    </svg>
    <div class="radar-legend">
      <span><i class="dot" style="background:#cf8427"></i>固定块（考研/保研）</span>
      <span><i class="dot" style="background:#146356"></i>常规学习/项目</span>
      <span><i class="dot" style="background:#2f9e8f"></i>持续投入（刷题/英语）</span>
      <span><i class="dot" style="background:transparent;border:1px dashed #b14a3c"></i>预算线</span>
    </div>`;
}

// ============ 可视化：四年成长路线时间轴 ============
function renderRouteTimeline(plan, profile) {
  if (!plan || !plan.semester_plans || !plan.semester_plans.length) return;
  const start = profile.semester || 1;
  const semesters = plan.semester_plans;
  const W = 760, colGap = 8, padL = 14, padT = 46, padB = 10;
  const colW = Math.floor((W - padL * 2 - colGap * (semesters.length - 1)) / semesters.length);
  const maxH = 360;
  // 收集所有活动名 → 图例色（按类型）
  const typeColor = { fixed: "#cf8427", internship: "#2f6f8f", exam_prep: "#cf8427", default: "#146356" };
  let cols = "";
  semesters.forEach((sp, i) => {
    const x = padL + i * (colW + colGap);
    const items = [...sp.scheduled, ...sp.fixed];
    const cellH = Math.min(28, maxH / Math.max(1, items.length));
    let cells = "";
    items.forEach((it, j) => {
      const y = padT + j * (cellH + 4);
      const color = it.status === "fixed" ? typeColor.fixed : (it.type === "internship" ? typeColor.internship : typeColor.default);
      cells += `<rect x="${x}" y="${y}" width="${colW - 4}" height="${cellH}" rx="5" fill="${color}">
        <title>${esc(it.name)}（${it.workload_hours}h）</title></rect>`;
    });
    cols += `
      <text x="${x + (colW - 4) / 2}" y="${padT - 14}" text-anchor="middle" class="tl-sem">第 ${sp.semester} 学期</text>
      <text x="${x + (colW - 4) / 2}" y="${padT - 2}" text-anchor="middle" class="tl-hrs">${sp.total_hours}h/${sp.budget_hours}h</text>
      ${cells}`;
  });
  // 暑期块放在最后一行
  let summerRow = "";
  const summerY = padT + Math.ceil(Math.max(...semesters.map((s) => s.scheduled.length + s.fixed.length))) * (cellH + 4) + 6;
  plan.summer_blocks.forEach((b) => {
    summerRow += `<g><rect x="${padL}" y="${summerY}" width="200" height="24" rx="5" class="summer-pill"></rect>
      <text x="${padL + 10}" y="${summerY + 16}" class="summer-txt">暑期·${esc(b.name)}</text></g>`;
  });
  const H = summerY + 50;
  $("#timeline-card").classList.remove("hidden");
  $("#route-timeline").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:${W}px" role="img">${cols}${summerRow}</svg>
    <div class="radar-legend">
      <span><i class="dot dot-def"></i>常规学习/项目</span>
      <span><i class="dot dot-fixed"></i>固定块（考研/保研）</span>
      <span><i class="dot dot-intern"></i>暑期实习</span>
    </div>`;
}

// ---------- 成长路线 ----------
$("#btn-generate").addEventListener("click", async () => {
  flash($("#plan-msg"), true, "生成中…");
  const r = await api("/api/tool/generate_plan", {});
  if (!r.ok) return flash($("#plan-msg"), false, r.message || JSON.stringify(r.error));
  flash($("#plan-msg"), true, `${r.plan_id} 已生成（${r.semesters} 个学期）`);
  const latest = await api("/api/plan/latest");
  renderPlan(latest.plan);
});

function renderPlan(plan) {
  const el = $("#plan-view");
  el.innerHTML = `
    ${plan.semester_plans.map((sp) => {
      const pct = Math.min(100, (sp.total_hours / sp.budget_hours) * 100);
      const fixedHeavy = sp.fixed.length > 0;
      return `
      <div class="semester-card ${fixedHeavy ? "fixed-heavy" : ""}">
        <div class="sem-head">
          <h3>第 ${sp.semester} 学期</h3>
          <span class="hint" style="margin:0">预算 ${sp.budget_hours}h · 已排 ${sp.total_hours}h · 余 ${sp.remaining_budget}h</span>
        </div>
        <div class="budget-bar"><div class="budget-fill" style="width:${pct}%"></div></div>
        ${[...sp.fixed, ...sp.scheduled].map((item) => `
          <div class="task-row">
            <span>${esc(item.name)} ${item.status === "fixed" ? '<span class="fam-tag fam-ai">固定块</span>' : ""}</span>
            <span class="wh">${item.workload_hours}h</span>
            <div class="task-detail">覆盖能力：${esc(item.covers_skills.join(", "))}<br>
              交付物：${esc(item.deliverable)}<br>验收：${esc(item.acceptance)}</div>
          </div>`).join("") || '<p class="hint">本学期无安排（预算可能被固定块占用）。</p>'}
      </div>`;
    }).join("")}
    ${plan.summer_blocks.map((b) => `
      <div class="semester-card summer-card">
        <div class="sem-head"><h3>暑期（第 ${b.after_semester} 学期后）</h3><span class="wh">${b.workload_hours}h</span></div>
        <div class="task-detail">${esc(b.name)}<br>交付：${esc(b.deliverable)}<br>验收：${esc(b.acceptance)}</div>
      </div>`).join("")}
    <div class="card">
      <h3>未来四周任务（每周不超预算）</h3>
      <div class="table-wrap"><table class="week-table">
        <thead><tr><th>周次</th><th>任务</th><th>工时</th><th>交付物 / 验收</th></tr></thead>
        <tbody>${plan.near_term.weeks.map((w) => `
          <tr><td>第 ${w.week} 周（${w.week_hours}h）</td>
            <td>${w.tasks.map((t) => esc(t.task_name)).join("<br>") || "—"}</td>
            <td>${w.tasks.map((t) => t.hours + "h").join("<br>") || "—"}</td>
            <td class="task-detail">${w.tasks.map((t) => `${esc(t.deliverable)}<br>验收：${esc(t.acceptance)}`).join("<hr style='border:none;border-top:1px dashed #ccc'>") || "—"}</td>
          </tr>`).join("")}
        </tbody></table></div>
    </div>
    ${plan.unallocated.length ? `
      <div class="unalloc">
        <h3>预算内无法安排的活动（系统不把冲突计划标记为可执行）</h3>
        <ul>${plan.unallocated.map((u) => `
          <li><strong>${esc(u.name)}</strong>：${esc(u.reason)}<br>可选：${u.options.map(esc).join(" / ")}</li>`).join("")}
        </ul>
      </div>` : ""}
    <div class="card">
      <h3>规则校验结果（${plan.validation.passed ? "全部通过，计划可采用" : "存在失败项"}）</h3>
      <p class="check-pill">${plan.validation.checks.map((c) =>
        `<span class="${c.passed ? "pass" : "fail"}">${c.passed ? "✓" : "✗"} ${esc(c.check)}</span>`).join("　")}</p>
    </div>`;
  renderCharts(plan);
}

// 渲染成长路线配套图表（雷达图 + 时间轴 + 工作量堆叠）
async function renderCharts(plan) {
  try {
    const profile = STATE.profile || {};
    renderRouteTimeline(plan, profile);
    renderWorkloadChart(plan);
    const g = await api("/api/tool/get_gap", {});
    if (g.ok) {
      renderGapChart(g.gap, profile.mastered_skills || []);
      renderPriorityMatrix(g.gap);
    }
  } catch (e) { /* 图表失败不影响主体内容 */ }
}

// ---------- 反馈调整 ----------
async function renderCompletionList() {
  const latest = await api("/api/plan/latest");
  const el = $("#completion-list");
  if (!latest.ok) { el.innerHTML = '<p class="hint">请先生成计划。</p>'; return; }
  const done = new Set(STATE.completions || []);
  const items = [];
  latest.plan.semester_plans.forEach((sp) =>
    [...sp.fixed, ...sp.scheduled].forEach((i) => items.push(i)));
  latest.plan.summer_blocks.forEach((b) => items.push({ activity_id: b.activity_id, name: b.name }));
  el.innerHTML = items.map((i) => `
    <div class="completion-item">
      <label><input type="checkbox" data-aid="${esc(i.activity_id)}" ${done.has(i.activity_id) ? "checked" : ""}>
        ${esc(i.name)}（${esc(i.activity_id)}）</label>
      <input type="text" class="ev-input" data-aid="${esc(i.activity_id)}" placeholder="完成后填写成果证据，如「Git 仓库链接 / 证书编号」">
    </div>`).join("");
  $$("#completion-list input[type=checkbox]").forEach((cb) => cb.addEventListener("change", async () => {
    if (cb.checked) {
      const ev = document.querySelector(`.ev-input[data-aid="${cb.dataset.aid}"]`).value.trim();
      const r = await api("/api/tool/update_completion", { activity_id: cb.dataset.aid, evidence: ev });
      if (!r.ok) { cb.checked = false; return; }
      if (r.promoted_skills && r.promoted_skills.length) {
        flash($("#adjust-msg"), true, `已掌握能力：${r.promoted_skills.join("、")}`);
      }
    }
    STATE = await api("/api/state");
  }));
}

$("#btn-adjust").addEventListener("click", async () => {
  const args = {};
  if ($("#adj-family").value) args.target_family = $("#adj-family").value;
  if ($("#adj-hours").value !== "") args.weekly_hours = Number($("#adj-hours").value);
  if ($("#adj-path").value) args.path = $("#adj-path").value;
  if (!Object.keys(args).length) return flash($("#adjust-msg"), false, "请至少选择一项调整");
  const r = await api("/api/tool/adjust_conditions", args);
  if (!r.ok) return flash($("#adjust-msg"), false, r.message || JSON.stringify(r.error));
  flash($("#adjust-msg"), true, `V${r.version} 已生成`);
  STATE = await api("/api/state");
  renderDiff(r.diff);
  const latest = await api("/api/plan/latest");
  if (latest.ok) renderPlan(latest.plan);
});

function renderDiff(d) {
  const groups = [
    ["added", "新增", "diff-added"], ["kept", "保留", "diff-kept"],
    ["deferred", "延期", "diff-deferred"], ["removed", "移除", "diff-removed"],
  ];
  $("#diff-view").innerHTML = `
    <p class="hint">${esc(d.impact)}</p>
    ${groups.map(([key, label, cls]) => `
      <div class="diff-group ${cls}">
        <h4>${label}（${d[key].length}）</h4>
        ${d[key].map((x) => `<span class="diff-chip">${esc(x.activity_id)}
          ${x.from !== undefined ? `${esc(x.from)} → ${esc(x.to)}` : esc(x.semester ?? "")}</span>`).join("") || '<span class="hint">无</span>'}
      </div>`).join("")}`;
}

// ---------- 对话 ----------
function addMsg(role, text, err) {
  const d = document.createElement("div");
  d.className = "msg msg-" + role + (err ? " err" : "");
  d.textContent = text;
  $("#chat-box").appendChild(d);
  $("#chat-box").scrollTop = $("#chat-box").scrollHeight;
}
async function sendChat() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  addMsg("user", text);
  input.value = "";
  const btn = $("#btn-chat-send");
  btn.disabled = true;
  // 加载提示：本地模型 CPU 推理较慢，避免用户误以为卡死
  const thinking = document.createElement("div");
  thinking.className = "msg msg-agent thinking";
  thinking.textContent = "Agent 正在思考…";
  $("#chat-box").appendChild(thinking);
  $("#chat-box").scrollTop = $("#chat-box").scrollHeight;
  let r;
  try {
    r = await api("/api/chat", { message: text });
  } finally {
    thinking.remove();
    btn.disabled = false;
  }
  const trace = (r.trace || []).map((t) => `[${t.step}] ${t.tool_name} ${t.ok ? "✓" : "✗" + (t.error ? "（" + t.error + "）" : "")}`).join("\n");
  addMsg("agent", r.answer + (trace ? "\n\n工具链：\n" + trace : ""), !r.ok);
  loadRecords();
}
$("#btn-chat-send").addEventListener("click", sendChat);
$("#chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
$$(".chip").forEach((c) => c.addEventListener("click", () => {
  $("#chat-input").value = c.dataset.msg; sendChat();
}));

async function loadRecords() {
  const r = await api("/api/records");
  const rows = r.records.slice().reverse().slice(0, 60);
  $("#records-table tbody").innerHTML = rows.map((x) => `
    <tr>
      <td>${x.seq}</td><td>${esc(x.trigger)}</td><td>${esc(x.tool_name)}</td>
      <td style="max-width:220px;word-break:break-all">${esc(JSON.stringify(x.arguments))}</td>
      <td style="max-width:240px;word-break:break-all">${esc(x.error ? JSON.stringify(x.error) : x.result_summary || "ok")}</td>
      <td>${esc(x.model_mode)}</td>
    </tr>`).join("");
}
$("#btn-refresh-records").addEventListener("click", loadRecords);

// ---------- 报告 ----------
$("#btn-export").addEventListener("click", async () => {
  const r = await api("/api/tool/export_report", {});
  if (!r.ok) { alert(r.message); return; }
  $("#report-preview").textContent = r.report_markdown;
  $("#report-preview").classList.remove("hidden");
  downloadText(r.filename, r.report_markdown);
});

// ---------- 重置 ----------
$("#btn-reset").addEventListener("click", async () => {
  if (!confirm("确定清空全部本地状态？")) return;
  await api("/api/reset", {});
  location.reload();
});

init();
