const API = "";

/** @type {{id:string,role:string,html:string}[]} */
let chatMessages = [];
let clarifySessionId = null;
let pendingQueryBody = null;
let draftRules = [];
let busy = false;
/** 开=多轮追问；关=静默自动理解 query */
let interactiveClarify = true;

function toggleInteractiveClarify() {
  interactiveClarify = !interactiveClarify;
  const btn = document.getElementById("qa-clarify-toggle");
  if (!btn) return;
  if (interactiveClarify) {
    btn.classList.add("on");
    btn.classList.remove("off");
    btn.textContent = "开 · 多轮追问";
  } else {
    btn.classList.add("off");
    btn.classList.remove("on");
    btn.textContent = "关 · 自动理解";
    setClarifyBar(false);
  }
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const name = btn.dataset.tab;
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.add("hidden"));
    document.getElementById("tab-" + name).classList.remove("hidden");
  });
});

document.getElementById("qa-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendQuery();
  }
});
document.getElementById("qa-clarify-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendClarifyReply();
  }
});

async function refreshHealth() {
  const badge = document.getElementById("health-badge");
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch(API + "/api/health", { signal: ctrl.signal });
    clearTimeout(t);
    const d = await r.json();
    const es = d.elasticsearch && d.elasticsearch.ok ? "ES✓" : "ES✗";
    const rag = d.rag_core && d.rag_core.ok ? "RAG✓" : "RAG✗";
    const rules = d.local_rules ? "Rules✓" : "Rules·";
    badge.textContent = es + " · " + rag + " · " + rules;
    badge.className = "badge " + (d.elasticsearch && d.elasticsearch.ok ? "ok" : "bad");
  } catch (e) {
    badge.textContent = "服务异常/超时";
    badge.className = "badge bad";
  }
}

async function loadSettings() {
  const r = await fetch(API + "/api/settings");
  const d = await r.json();
  document.getElementById("s-llm-url").value = d.llm_base_url || "";
  document.getElementById("s-llm-key").value = d.llm_api_key || "";
  document.getElementById("s-llm-model").value = d.llm_model || "";
  document.getElementById("s-rag-url").value = d.rag_base_url || "";
  document.getElementById("s-rag-key").value = d.rag_access_key || "";
  document.getElementById("s-rag-kb").value = d.rag_kb_id || "";
  document.getElementById("s-es-hosts").value = (d.es_hosts || []).join(",");
  document.getElementById("s-es-user").value = d.es_username || "";
  document.getElementById("s-es-pass").value = d.es_password || "";
  document.getElementById("s-es-index").value = d.es_default_index || "*";
}

/** 从 configs/datasources.yaml（经 /api/datasources）填充下拉，客户新增库无需改前端枚举。 */
async function loadDatasources() {
  const ids = ["qa-ds", "rules-ds", "cons-ds"];
  try {
    const r = await fetch(API + "/api/datasources");
    const d = await r.json();
    const map = d.datasources || {};
    const entries = Object.entries(map)
      .filter(([, cfg]) => cfg && cfg.enabled !== false)
      .sort(([a], [b]) => a.localeCompare(b));
    if (!entries.length) {
      ids.forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<option value="">无可用数据源</option>';
      });
      return;
    }
    const preferred =
      localStorage.getItem("nl2sql_datasource") ||
      (map["local-es"] && map["local-es"].enabled !== false ? "local-es" : entries[0][0]);
    const opts = entries
      .map(([id, cfg]) => {
        const type = cfg.type || "?";
        const label = id === preferred ? `${id}（${type}）` : `${id}（${type}）`;
        return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
      })
      .join("");
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = opts;
      if (map[preferred]) el.value = preferred;
      el.onchange = () => localStorage.setItem("nl2sql_datasource", el.value);
    });
  } catch (e) {
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<option value="">数据源加载失败</option>';
    });
  }
}

async function saveSettings() {
  const body = {
    llm_base_url: document.getElementById("s-llm-url").value.trim(),
    llm_api_key: document.getElementById("s-llm-key").value.trim(),
    llm_model: document.getElementById("s-llm-model").value.trim(),
    rag_base_url: document.getElementById("s-rag-url").value.trim(),
    rag_access_key: document.getElementById("s-rag-key").value.trim(),
    rag_kb_id: document.getElementById("s-rag-kb").value.trim(),
    es_hosts: document.getElementById("s-es-hosts").value.split(",").map((s) => s.trim()).filter(Boolean),
    es_username: document.getElementById("s-es-user").value.trim(),
    es_password: document.getElementById("s-es-pass").value,
    es_default_index: document.getElementById("s-es-index").value.trim() || "*",
  };
  const r = await fetch(API + "/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  document.getElementById("save-msg").textContent = d.ok ? "已保存" : "保存失败";
  refreshHealth();
}

async function testEs() {
  const ds = document.getElementById("qa-ds")?.value || "local-es";
  const r = await fetch(API + "/api/datasources/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ datasource_id: ds }),
  });
  const d = await r.json();
  document.getElementById("es-test-msg").textContent = d.ok
    ? `连接成功（${ds}）`
    : `失败（${ds}）: ` + (d.error || "");
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatSql(sql) {
  if (!sql || typeof sql !== "string") return sql;
  const keywords = [
    "SELECT", "FROM", "WHERE", "AND", "OR", "GROUP BY", "HAVING",
    "ORDER BY", "LIMIT", "LEFT JOIN", "INNER JOIN", "JOIN", "ON", "UNION", "IN",
  ];
  let s = sql.replace(/\s+/g, " ").trim();
  keywords.sort((a, b) => b.length - a.length);
  for (const kw of keywords) {
    const re = new RegExp("\\b" + kw.replace(/ /g, "\\s+") + "\\b", "gi");
    s = s.replace(re, (m) => "\n" + m.toUpperCase());
  }
  const lines = s.split("\n").map((line) => line.trim()).filter(Boolean);
  let depth = 0;
  const out = [];
  for (const line of lines) {
    if (line.startsWith(")")) depth = Math.max(0, depth - 1);
    out.push("  ".repeat(depth) + line);
    const opens = (line.match(/\(/g) || []).length;
    const closes = (line.match(/\)/g) || []).length;
    depth = Math.max(0, depth + opens - closes);
  }
  return out.join("\n");
}

function formatQueryDisplay(q) {
  if (typeof q === "string") {
    const t = q.trim();
    if (t.startsWith("{")) {
      try { return JSON.stringify(JSON.parse(t), null, 2); } catch (e) { return formatSql(t); }
    }
    return formatSql(t);
  }
  return JSON.stringify(q, null, 2);
}

function renderChat() {
  const el = document.getElementById("qa-chat");
  el.innerHTML = chatMessages.map((m) =>
    `<div class="bubble ${m.role}" data-id="${m.id}">${m.html}</div>`
  ).join("");
  el.scrollTop = el.scrollHeight;
}

function appendBubble(role, html) {
  const id = "m" + Date.now() + Math.random().toString(36).slice(2, 7);
  chatMessages.push({ id, role, html });
  renderChat();
  return id;
}

function updateBubble(id, html) {
  const m = chatMessages.find((x) => x.id === id);
  if (!m) return;
  m.html = html;
  renderChat();
}

function setClarifyBar(show, hint) {
  const bar = document.getElementById("qa-clarify-bar");
  if (show) {
    bar.classList.remove("hidden");
    if (hint) document.getElementById("qa-clarify-hint").textContent = hint;
    document.getElementById("qa-clarify-input").focus();
  } else {
    bar.classList.add("hidden");
    document.getElementById("qa-clarify-input").value = "";
  }
}

function clearChat() {
  chatMessages = [];
  clarifySessionId = null;
  pendingQueryBody = null;
  setClarifyBar(false);
  renderChat();
}

function renderResultHtml(d) {
  if (d.error) {
    let html = `<p class="err">${escapeHtml(d.error)}</p>`;
    if (d.generated_query) {
      html += `<pre class="code tight">${escapeHtml(formatQueryDisplay(d.generated_query))}</pre>`;
    }
    return html;
  }
  const result = d.result || d;
  let html = `<div class="muted">${result.row_count || 0} 行 · mode=${result.mode || d.mode || ""}</div>`;
  if (d.generated_query) {
    html += `<pre class="code tight">${escapeHtml(formatQueryDisplay(d.generated_query))}</pre>`;
  }
  if (result.columns && result.columns.length) {
    const hide = new Set(["_score", "_index", "score", "index"]);
    const cols = result.columns.map((c, i) => ({ c, i })).filter(({ c }) => !hide.has(String(c)));
    const idIdx = cols.find(({ c }) => c === "_id");
    let dropId = false;
    if (idIdx) {
      const sample = (result.rows || []).slice(0, 10);
      dropId = sample.length > 0 && sample.every((row) => {
        const idVal = String(row[idIdx.i] ?? "");
        return row.some((cell, j) => j !== idIdx.i && String(cell ?? "") === idVal);
      });
    }
    const vis = dropId ? cols.filter(({ c }) => c !== "_id") : cols;
    html += '<div class="table-wrap"><table><tr>' + vis.map(({ c }) => `<th>${escapeHtml(c)}</th>`).join("") + "</tr>";
    (result.rows || []).slice(0, 50).forEach((row) => {
      html += "<tr>" + vis.map(({ i }) => {
        const s = row[i] == null ? "" : String(row[i]);
        return `<td title="${escapeHtml(s)}">${escapeHtml(s)}</td>`;
      }).join("") + "</tr>";
    });
    html += "</table></div>";
  } else if ((result.row_count || 0) === 0) {
    html += `<p class="muted">无命中行。</p>`;
  }
  if (result.warnings && result.warnings.length) {
    html += `<p class="muted">${escapeHtml(result.warnings.join("；"))}</p>`;
  }
  return html;
}

function buildQueryBody(extra) {
  let exec = document.getElementById("qa-exec").value.trim();
  let execute_query = null;
  if (exec) {
    if (exec.startsWith("{")) {
      try { execute_query = JSON.parse(exec); } catch (e) { throw new Error("DSL JSON 解析失败"); }
    } else execute_query = exec;
  }
  const q = document.getElementById("qa-input").value.trim();
  return {
    query: q || "(empty)",
    datasource_id: document.getElementById("qa-ds").value,
    execute_query,
    mode: document.getElementById("qa-mode").value,
    use_llm: document.getElementById("qa-llm").value === "1" && !execute_query,
    skip_clarify: !!execute_query,
    interactive_clarify: interactiveClarify,
    ...extra,
  };
}

async function consumeSse(body, assistantId) {
  const r = await fetch(API + "/api/query/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || ("HTTP " + r.status));
  }

  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let stepsHtml = "";
  let sqlHtml = "";
  let statusLine = "处理中…";
  let finalPayload = null;
  let needClarify = false;

  const paint = () => {
    updateBubble(
      assistantId,
      `<div class="muted">${escapeHtml(statusLine)}</div>${stepsHtml}${sqlHtml}` +
        (finalPayload ? renderResultHtml(finalPayload) : "")
    );
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      if (!chunk.trim()) continue;
      let event = "message";
      let dataStr = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataStr += line.slice(5).trim();
      }
      let data = {};
      try { data = JSON.parse(dataStr || "{}"); } catch (e) { data = { raw: dataStr }; }

      if (event === "status") {
        statusLine = data.message || statusLine;
      } else if (event === "need_clarify") {
        needClarify = true;
        clarifySessionId = data.clarify_session && data.clarify_session.id;
        const q = data.question || (data.clarify_session && data.clarify_session.messages || []).slice(-1)[0]?.content || "请补充条件";
        statusLine = "需要澄清";
        stepsHtml += `<div class="clarify-q">${escapeHtml(q)}</div>`;
        const rounds = data.clarify_session
          ? `（第 ${data.clarify_session.round_count || 1}/${data.clarify_session.max_rounds || 3} 轮）`
          : "";
        setClarifyBar(true, "请回答澄清问题" + rounds);
        pendingQueryBody = { ...body };
      } else if (event === "resolved_query") {
        const auto = data.auto || data.interactive_clarify === false;
        statusLine = (auto ? "自动理解：" : "已确认：") + (data.resolved_query || "");
        const note = data.note ? `<div class="muted">${escapeHtml(data.note)}</div>` : "";
        stepsHtml += `<div class="muted">${auto ? "auto" : "resolved"}：${escapeHtml(data.resolved_query || "")}</div>${note}`;
        setClarifyBar(false);
        clarifySessionId = null;
      } else if (event === "step") {
        const s = data.step || data;
        stepsHtml += `<div class="step ${s.status || ""}"><b>${escapeHtml(s.name || "")}</b> · ${escapeHtml(s.status || "")}<div class="muted">${escapeHtml(s.message || "")}</div></div>`;
        statusLine = (s.name || "step") + " · " + (s.status || "");
      } else if (event === "rules") {
        stepsHtml += `<div class="muted">召回规则 ${data.count || 0} 条</div>`;
      } else if (event === "sql") {
        sqlHtml = `<pre class="code tight">${escapeHtml(formatQueryDisplay(data.query))}</pre>`;
      } else if (event === "retry") {
        stepsHtml += `<div class="step error"><b>retry #${data.attempt || "?"}</b><div class="muted">${escapeHtml(data.feedback || "")}</div></div>`;
      } else if (event === "result") {
        const res = data.result || data;
        finalPayload = {
          result: {
            columns: res.columns,
            rows: res.rows,
            row_count: res.row_count,
            mode: res.mode || data.mode,
            warnings: res.warnings,
          },
          generated_query: data.generated_query,
          mode: data.mode || res.mode,
          error: data.error || null,
        };
        statusLine = "完成";
      } else if (event === "error") {
        finalPayload = { error: data.message || "error", generated_query: data.generated_query };
        statusLine = "出错";
      } else if (event === "done") {
        if (!needClarify && !finalPayload && data.ok === false) {
          finalPayload = { error: "未完成" };
        }
      }
      paint();
    }
  }
  paint();
  return { needClarify };
}

async function sendQuery() {
  if (busy) return;
  const q = document.getElementById("qa-input").value.trim();
  const exec = document.getElementById("qa-exec").value.trim();
  if (!q && !exec) return alert("请输入问题或直接执行查询");

  let body;
  try {
    body = buildQueryBody({});
  } catch (e) {
    return alert(e.message);
  }

  busy = true;
  document.getElementById("qa-send").disabled = true;
  appendBubble("user", `<div>${escapeHtml(q || "(直接执行)")}</div>`);
  const aid = appendBubble("assistant", `<div class="muted">…</div>`);
  document.getElementById("qa-input").value = "";

  try {
    await consumeSse(body, aid);
  } catch (e) {
    updateBubble(aid, `<p class="err">${escapeHtml(e.message || e)}</p>`);
  } finally {
    busy = false;
    document.getElementById("qa-send").disabled = false;
  }
}

async function sendClarifyReply() {
  if (busy || !clarifySessionId || !pendingQueryBody) return;
  const msg = document.getElementById("qa-clarify-input").value.trim();
  if (!msg) return;

  busy = true;
  appendBubble("user", `<div>${escapeHtml(msg)}</div>`);
  const aid = appendBubble("assistant", `<div class="muted">继续…</div>`);
  setClarifyBar(false);

  const body = {
    ...pendingQueryBody,
    clarify_session_id: clarifySessionId,
    clarify_message: msg,
  };
  pendingQueryBody = null;

  try {
    await consumeSse(body, aid);
  } catch (e) {
    updateBubble(aid, `<p class="err">${escapeHtml(e.message || e)}</p>`);
  } finally {
    busy = false;
  }
}

/* ---------- 规则中心 ---------- */

function renderDraftRules() {
  const el = document.getElementById("rules-draft");
  if (!draftRules.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <div class="btn-group" style="margin-top:0">
      <button class="btn btn-default" type="button" onclick="toggleAllDraft(true)">全选</button>
      <button class="btn btn-default" type="button" onclick="toggleAllDraft(false)">全不选</button>
      <span class="muted">共 ${draftRules.length} 条候选</span>
    </div>
    ${draftRules.map((r, i) => `
      <div class="draft-item">
        <label class="draft-check"><input type="checkbox" class="draft-cb" data-i="${i}" checked> 导入</label>
        <textarea class="draft-ta" data-i="${i}" rows="6">${escapeHtml(JSON.stringify(r, null, 2))}</textarea>
        <button class="btn btn-default" type="button" onclick="removeDraft(${i})">删除</button>
      </div>
    `).join("")}
  `;
}

function toggleAllDraft(on) {
  document.querySelectorAll(".draft-cb").forEach((cb) => { cb.checked = on; });
}

function removeDraft(i) {
  syncDraftFromDom();
  draftRules.splice(i, 1);
  renderDraftRules();
}

function syncDraftFromDom() {
  document.querySelectorAll(".draft-ta").forEach((ta) => {
    const i = Number(ta.dataset.i);
    try {
      draftRules[i] = JSON.parse(ta.value);
    } catch (e) {
      /* 保留原对象，导入时再校验 */
    }
  });
}

function collectSelectedDraft() {
  syncDraftFromDom();
  const selected = [];
  document.querySelectorAll(".draft-cb").forEach((cb) => {
    if (!cb.checked) return;
    const i = Number(cb.dataset.i);
    const ta = document.querySelector(`.draft-ta[data-i="${i}"]`);
    try {
      selected.push(JSON.parse(ta.value));
    } catch (e) {
      throw new Error("第 " + (i + 1) + " 条 JSON 无效");
    }
  });
  return selected;
}

async function generateRulesNl() {
  const user_text = document.getElementById("rules-nl").value.trim();
  if (!user_text) return alert("请输入业务描述");
  document.getElementById("rules-msg").textContent = "生成中…";
  const r = await fetch(API + "/api/rules/generate_from_nl", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      database_id: document.getElementById("rules-ds").value,
      user_text,
      include_schema: document.getElementById("rules-schema-opt").value === "1",
    }),
  });
  const d = await r.json();
  if (!r.ok) {
    document.getElementById("rules-msg").textContent = d.detail || "生成失败";
    return;
  }
  draftRules = d.rules || [];
  renderDraftRules();
  document.getElementById("rules-msg").textContent = `已生成 ${draftRules.length} 条，请编辑后勾选导入`;
}

async function importSelectedRules() {
  let rules;
  try {
    rules = collectSelectedDraft();
  } catch (e) {
    return alert(e.message);
  }
  if (!rules.length) return alert("请至少勾选一条");
  document.getElementById("rules-msg").textContent = "导入中…";
  const r = await fetch(API + "/api/rules/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      database_id: document.getElementById("rules-ds").value,
      rules,
      sync_rag: true,
    }),
  });
  const d = await r.json();
  if (!r.ok) {
    document.getElementById("rules-msg").textContent = d.detail || "导入失败";
    return;
  }
  document.getElementById("rules-msg").textContent =
    `本地 ${d.imported_local} 条；RAG: ${JSON.stringify(d.rag)}`;
  loadRules();
  refreshHealth();
}

async function importRulesFile(ev) {
  const file = ev.target.files && ev.target.files[0];
  ev.target.value = "";
  if (!file) return;
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const arr = Array.isArray(parsed) ? parsed : (parsed.rules || []);
    if (!arr.length) return alert("JSON 中无规则数组");
    draftRules = arr;
    renderDraftRules();
    document.getElementById("rules-msg").textContent = `已载入文件 ${arr.length} 条，请勾选后导入`;
  } catch (e) {
    alert("文件解析失败: " + e.message);
  }
}

async function bootstrapRules() {
  document.getElementById("rules-msg").textContent = "初始化中…";
  const r = await fetch(API + "/api/rules/bootstrap", { method: "POST" });
  const d = await r.json();
  document.getElementById("rules-msg").textContent = d.ok ? `已写入 ${d.count} 条 -> ${d.path}` : JSON.stringify(d);
  loadRules();
  refreshHealth();
}

async function loadRules() {
  const ds = document.getElementById("rules-ds")?.value || "local-es";
  const r = await fetch(API + "/api/rules?database_id=" + encodeURIComponent(ds));
  const d = await r.json();
  document.getElementById("rules-list").textContent =
    `共 ${d.count} 条\n` + JSON.stringify((d.rules || []).slice(0, 30), null, 2);
}

async function loadSchema() {
  const ds = document.getElementById("rules-ds")?.value || "local-es";
  const r = await fetch(API + "/api/schema/" + encodeURIComponent(ds));
  const d = await r.json();
  document.getElementById("rules-schema").textContent = JSON.stringify(d, null, 2);
}

/* ---------- 一致性 ---------- */

async function runConsistency() {
  const query = document.getElementById("cons-q").value.trim();
  if (!query) return alert("请输入问句");
  const out = document.getElementById("cons-out");
  out.innerHTML = '<p class="muted">运行中…</p>';
  const r = await fetch(API + "/api/consistency/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      datasource_id: document.getElementById("cons-ds").value,
      mode: document.getElementById("cons-mode").value,
      repeats: Number(document.getElementById("cons-n").value) || 3,
    }),
  });
  const d = await r.json();
  if (!r.ok) {
    out.innerHTML = `<p class="err">${escapeHtml(d.detail || "失败")}</p>`;
    return;
  }
  const score = d.result_consistency;
  const pct = typeof score === "number" ? (score * 100).toFixed(1) + "%" : "-";
  let html = `<div class="card inner">
    <h3>结果一致性 ${pct}</h3>
    <p class="muted">有效 ${d.valid_runs} / 无效 ${d.invalid_runs} · 共 ${d.repeats} 次</p>
  </div>`;
  (d.runs || []).forEach((run) => {
    html += `<div class="step ${run.invalid ? "error" : "done"}">
      <b>#${run.run}</b> · ${run.invalid ? "无效" : (run.row_count + " 行")}
      ${run.error ? `<div class="err">${escapeHtml(run.error)}</div>` : ""}
      ${run.generated_query ? `<pre class="code tight">${escapeHtml(formatQueryDisplay(run.generated_query))}</pre>` : ""}
    </div>`;
  });
  out.innerHTML = html;
}

refreshHealth();
loadSettings();
loadDatasources();
setInterval(refreshHealth, 15000);
