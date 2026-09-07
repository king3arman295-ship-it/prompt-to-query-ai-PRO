const API = "";
let currentDB = null;
let lastSQL = "";
let lastRows = [];
let lastColumns = [];
let history = JSON.parse(localStorage.getItem("queryHistory") || "[]");

// ---------- Helpers ----------
async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.message || res.statusText);
  return data;
}
function $(id) { return document.getElementById(id); }
function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }
function openModal(id) { $(id).classList.remove("hidden"); }
function closeModal(id) { $(id).classList.add("hidden"); }

function showTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  $("tab-" + name).classList.add("active");
  const btn = document.querySelector(`.tab-btn[data-tab="${name}"]`);
  if (btn) btn.classList.add("active");
  if (name === "history") renderHistory();
  if (name === "schema" && currentDB) loadSchema();
}

// ---------- Connections ----------
async function refreshConnections() {
  try {
    const data = await api("/api/connections");
    const list = $("connection-list");
    if (!data.connections.length) {
      list.innerHTML = '<p class="muted">No databases yet.</p>';
      return;
    }
    list.innerHTML = data.connections.map(c => `
      <div class="conn-item ${currentDB === c.name ? "active" : ""}" onclick="selectDB('${c.name}')">
        <strong>${c.name}</strong>
        <span>${c.dialect || "?"} · ${c.table_count || 0} tables${c.description ? " · " + c.description : ""}</span>
      </div>
    `).join("");
  } catch (e) { console.error(e); }
}

function selectDB(name) {
  currentDB = name;
  $("current-db-title").textContent = name;
  $("current-db-meta").textContent = "Ready — ask anything in plain English";
  $("selected-actions").style.display = "block";
  refreshConnections();
  loadSchema();
}

async function refreshSchema() {
  if (!currentDB) return alert("Select a database first");
  try {
    $("current-db-meta").textContent = "Refreshing schema...";
    const res = await api(`/api/connections/${encodeURIComponent(currentDB)}/refresh-schema`, { method: "POST" });
    $("current-db-meta").textContent = `Schema refreshed · ${res.table_count} tables · ${res.scanned_at || ""}`;
    loadSchema();
    refreshConnections();
  } catch (e) {
    showError(e.message);
  }
}

async function deleteCurrentDB() {
  if (!currentDB) return;
  if (!confirm(`Remove connection "${currentDB}"?`)) return;
  try {
    await api(`/api/connections/${encodeURIComponent(currentDB)}`, { method: "DELETE" });
    currentDB = null;
    $("current-db-title").textContent = "Select a database to begin";
    $("current-db-meta").textContent = "";
    $("selected-actions").style.display = "none";
    $("schema-content").innerHTML = '<p class="muted">Select a database first.</p>';
    hide($("db-details"));
    refreshConnections();
  } catch (e) { alert(e.message); }
}

async function testDB() {
  const body = collectDBForm();
  $("db-msg").textContent = "Testing connection...";
  $("db-msg").className = "status";
  try {
    const res = await api("/api/connections/test", { method: "POST", body: JSON.stringify(body) });
    $("db-msg").textContent = res.message;
    $("db-msg").className = "status " + (res.success ? "ok" : "err");
  } catch (e) {
    $("db-msg").textContent = e.message;
    $("db-msg").className = "status err";
  }
}

async function saveDB() {
  const body = collectDBForm();
  if (!body.name || !body.database) {
    $("db-msg").textContent = "Name and database are required";
    $("db-msg").className = "status err";
    return;
  }
  $("db-msg").textContent = "Saving & scanning schema...";
  try {
    const res = await api("/api/connections", { method: "POST", body: JSON.stringify(body) });
    $("db-msg").textContent = res.message;
    $("db-msg").className = "status ok";
    closeModal("add-db-modal");
    await refreshConnections();
    selectDB(body.name);
  } catch (e) {
    $("db-msg").textContent = e.message;
    $("db-msg").className = "status err";
  }
}

function onDialectChange() {
  const d = $("db-dialect").value;
  const server = $("server-fields");
  const sqlite = $("sqlite-fields");
  if (d === "sqlite") {
    server.classList.add("hidden");
    sqlite.classList.remove("hidden");
  } else {
    sqlite.classList.add("hidden");
    server.classList.remove("hidden");
    // set default ports
    const ports = { postgresql: 5432, mysql: 3306, mssql: 1433 };
    $("db-port").value = ports[d] || 5432;
  }
}

function collectDBForm() {
  const dialect = $("db-dialect").value;
  if (dialect === "sqlite") {
    return {
      name: $("db-name").value.trim(),
      dialect: "sqlite",
      host: "localhost",
      port: null,
      database: $("db-sqlite-path").value.trim(),
      user: "",
      password: "",
      description: $("db-desc").value.trim(),
    };
  }
  return {
    name: $("db-name").value.trim(),
    dialect: dialect,
    host: $("db-host").value.trim() || "localhost",
    port: parseInt($("db-port").value) || null,
    database: $("db-database").value.trim(),
    user: $("db-user").value.trim(),
    password: $("db-password").value,
    description: $("db-desc").value.trim(),
  };
}

// ---------- LLM ----------
// The API key lives only on the server (.env) — the frontend never sees or
// sends it. This just shows a read-only status for the currently
// configured provider/model.
async function loadLLMStatus() {
  const el = $("llm-status-display");
  try {
    const res = await api("/api/llm/status");
    const keyInfo = res.api_key_configured ? `key loaded (${res.api_key_length} chars)` : "⚠️ no key loaded";
    el.textContent = `${res.provider} / ${res.model} — ${keyInfo} — ${res.message}`;
    el.className = "status " + (res.available && res.api_key_configured ? "ok" : "err");
  } catch (e) {
    el.textContent = e.message;
    el.className = "status err";
  }
}

// ---------- Progress loader ----------
const STEPS = ["validate", "generate", "execute", "format"];

function resetProgress() {
  STEPS.forEach((s) => {
    const el = $("step-" + s);
    if (!el) return;
    el.classList.remove("active", "done", "error");
    const icon = el.querySelector(".step-icon");
    if (icon) icon.textContent = String(STEPS.indexOf(s) + 1);
    const detail = $("detail-" + s);
    if (detail) detail.textContent = "";
  });
  const bar = $("progress-bar");
  if (bar) {
    bar.style.width = "0%";
    bar.classList.remove("indeterminate");
  }
}

function setStep(name, state, detailText) {
  // state: 'active' | 'done' | 'error'
  const idx = STEPS.indexOf(name);
  STEPS.forEach((s, i) => {
    const el = $("step-" + s);
    if (!el) return;
    el.classList.remove("active", "done", "error");
    const icon = el.querySelector(".step-icon");
    if (i < idx) {
      el.classList.add("done");
      if (icon) icon.textContent = "✓";
    } else if (i === idx) {
      el.classList.add(state);
      if (icon) {
        if (state === "done") icon.textContent = "✓";
        else if (state === "error") icon.textContent = "!";
        else icon.textContent = String(i + 1);
      }
    } else {
      if (icon) icon.textContent = String(i + 1);
    }
  });
  const detail = $("detail-" + name);
  if (detail && detailText) detail.textContent = "— " + detailText;

  const bar = $("progress-bar");
  if (bar) {
    const pct = state === "done" && name === "format" ? 100 : Math.round(((idx + (state === "done" ? 1 : 0.45)) / STEPS.length) * 100);
    bar.style.width = Math.min(pct, 100) + "%";
    bar.classList.toggle("indeterminate", state === "active");
  }
}

function setButtonsBusy(busy) {
  const run = $("btn-run");
  const sqlOnly = $("btn-sql-only");
  if (run) {
    run.disabled = busy;
    run.textContent = busy ? "Working..." : "Generate & Run";
  }
  if (sqlOnly) sqlOnly.disabled = busy;
}

// ---------- Query ----------
async function runQuery() {
  if (!currentDB) return alert("Select a database first");
  const question = $("question").value.trim();
  if (!question) return alert("Enter a question");

  hide($("error-box"));
  hide($("result-box"));
  hide($("sql-box"));
  show($("progress-box"));
  resetProgress();
  setButtonsBusy(true);

  try {
    setStep("validate", "active", "checking connection & question");
    await new Promise((r) => setTimeout(r, 280));
    setStep("validate", "done", "ok");

    setStep("generate", "active", "calling LLM...");
    const res = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({
        db_name: currentDB,
        question,
        limit: parseInt($("row-limit").value) || 200,
        execute: true,
      }),
    });

    setStep("generate", "done", "SQL ready");
    lastSQL = res.sql;
    $("generated-sql").value = res.sql;
    show($("sql-box"));

    setStep("execute", "active", "running on " + currentDB);
    await new Promise((r) => setTimeout(r, 200));
    setStep("execute", "done", (res.row_count != null ? res.row_count + " rows" : "done"));

    setStep("format", "active", "building table");
    renderResults(res);
    setStep("format", "done", "complete");
    addToHistory(question, res.sql, res.row_count);

    setTimeout(() => hide($("progress-box")), 900);
  } catch (e) {
    // Mark the current active step as error
    const active = document.querySelector(".progress-step.active");
    if (active) {
      const step = active.getAttribute("data-step");
      setStep(step, "error", "failed");
    } else {
      setStep("generate", "error", "failed");
    }
    $("generated-sql").value = "";
    showError(e.message);
  } finally {
    setButtonsBusy(false);
  }
}

async function generateOnly() {
  if (!currentDB) return alert("Select a database first");
  const question = $("question").value.trim();
  if (!question) return alert("Enter a question");

  hide($("error-box"));
  hide($("result-box"));
  show($("progress-box"));
  resetProgress();
  setButtonsBusy(true);

  try {
    setStep("validate", "active", "checking request");
    await new Promise((r) => setTimeout(r, 200));
    setStep("validate", "done", "ok");

    setStep("generate", "active", "calling LLM...");
    const res = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({ db_name: currentDB, question, execute: false }),
    });
    setStep("generate", "done", "SQL ready");
    // Skip execute/format for SQL-only
    setStep("execute", "done", "skipped");
    setStep("format", "done", "skipped");

    lastSQL = res.sql;
    $("generated-sql").value = res.sql;
    show($("sql-box"));
    setTimeout(() => hide($("progress-box")), 700);
  } catch (e) {
    setStep("generate", "error", "failed");
    showError(e.message);
  } finally {
    setButtonsBusy(false);
  }
}

async function executeSQL() {
  if (!currentDB) return;
  const sql = $("generated-sql").value.trim();
  if (!sql) return;

  hide($("error-box"));
  hide($("result-box"));
  show($("progress-box"));
  resetProgress();
  setButtonsBusy(true);

  try {
    setStep("validate", "done", "manual SQL");
    setStep("generate", "done", "using edited SQL");
    setStep("execute", "active", "running on " + currentDB);

    const res = await api("/api/execute", {
      method: "POST",
      body: JSON.stringify({
        db_name: currentDB,
        sql,
        limit: parseInt($("row-limit").value) || 200,
      }),
    });
    setStep("execute", "done", (res.row_count != null ? res.row_count + " rows" : "done"));
    setStep("format", "active", "building table");
    lastSQL = sql;
    renderResults(res);
    setStep("format", "done", "complete");
    addToHistory("(manual SQL)", sql, res.row_count);
    setTimeout(() => hide($("progress-box")), 800);
  } catch (e) {
    setStep("execute", "error", "failed");
    showError(e.message);
  } finally {
    setButtonsBusy(false);
  }
}

function renderResults(res) {
  lastRows = res.rows || [];
  lastColumns = res.columns || (lastRows[0] ? Object.keys(lastRows[0]) : []);
  $("row-count").textContent = res.row_count + " rows";
  const table = $("result-table");
  if (!lastRows.length) {
    table.innerHTML = "<tr><td>No rows returned</td></tr>";
  } else {
    table.innerHTML = `
      <thead><tr>${lastColumns.map(c => `<th>${c}</th>`).join("")}</tr></thead>
      <tbody>
        ${lastRows.map(row => `
          <tr>${lastColumns.map(c => `<td>${row[c] == null ? "" : escapeHtml(String(row[c]))}</td>`).join("")}</tr>
        `).join("")}
      </tbody>`;
  }
  show($("result-box"));
}

function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function showError(msg) {
  const box = $("error-box");
  box.textContent = msg;
  show(box);
}

// ---------- Downloads ----------
function downloadCSV() {
  if (!lastRows.length) return alert("No results to download");
  const lines = [lastColumns.join(",")];
  lastRows.forEach(r => {
    lines.push(lastColumns.map(c => {
      const v = r[c] == null ? "" : String(r[c]);
      return `"${v.replace(/"/g, '""')}"`;
    }).join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  triggerDownload(blob, "query_result.csv");
}

function downloadExcel() {
  if (!lastRows.length) return alert("No results to download");
  if (typeof XLSX === "undefined") {
    alert("Excel library not loaded. Use CSV instead.");
    return;
  }
  const ws = XLSX.utils.json_to_sheet(lastRows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Results");
  XLSX.writeFile(wb, "query_result.xlsx");
}

function downloadSQL() {
  if (!lastSQL) return alert("No SQL to download");
  const blob = new Blob([lastSQL], { type: "text/plain" });
  triggerDownload(blob, "query.sql");
}

function triggerDownload(blob, filename) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- History ----------
function addToHistory(question, sql, rows) {
  history.unshift({
    time: new Date().toLocaleString(),
    db: currentDB,
    question,
    sql,
    rows: rows || 0,
  });
  history = history.slice(0, 50);
  localStorage.setItem("queryHistory", JSON.stringify(history));
}

function renderHistory() {
  const box = $("history-list");
  if (!history.length) {
    box.innerHTML = '<p class="muted">No queries yet.</p>';
    return;
  }
  box.innerHTML = history.map((h, i) => `
    <div class="history-item">
      <div class="meta">${h.time} · ${h.db} · ${h.rows} rows</div>
      <div class="q">${escapeHtml(h.question)}</div>
      <pre>${escapeHtml(h.sql)}</pre>
      <button class="btn btn-sm btn-outline" onclick="rerunHistory(${i})">Re-run</button>
    </div>
  `).join("");
}

function rerunHistory(idx) {
  const h = history[idx];
  if (!h) return;
  if (h.db !== currentDB) {
    if (!confirm(`This query was on "${h.db}". Switch to it and run?`)) return;
    selectDB(h.db);
  }
  $("question").value = h.question;
  $("generated-sql").value = h.sql;
  show($("sql-box"));
  showTab("query");
  lastSQL = h.sql;
  executeSQL();
}

function clearHistory() {
  if (!confirm("Clear all history?")) return;
  history = [];
  localStorage.removeItem("queryHistory");
  renderHistory();
}

// ---------- Schema ----------
async function loadSchema() {
  if (!currentDB) return;
  const box = $("schema-content");
  const details = $("db-details");
  box.innerHTML = "<p class='muted'>Loading schema...</p>";
  try {
    const schema = await api("/api/schema/" + encodeURIComponent(currentDB));
    const tables = schema.tables || {};
    const tableNames = Object.keys(tables);

    show(details);
    details.innerHTML = `
      <div class="stat"><strong>${tableNames.length}</strong><span>Tables</span></div>
      <div class="stat"><strong>${schema.dialect || "—"}</strong><span>Dialect</span></div>
      <div class="stat"><strong>${(schema.views || []).length}</strong><span>Views</span></div>
      <div class="stat"><strong>${(schema.scanned_at || "—").slice(0,19).replace("T"," ")}</strong><span>Last Scan</span></div>
    `;

    if (!tableNames.length) {
      box.innerHTML = "<p class='muted'>No tables found.</p>";
      return;
    }
    box.innerHTML = tableNames.map(name => {
      const info = tables[name];
      const cols = info.columns || [];
      const pks = info.primary_keys || [];
      return `
        <details style="margin-bottom:0.6rem">
          <summary style="cursor:pointer;font-weight:500">${name} <span class="muted">(${cols.length} cols)</span></summary>
          <table style="margin-top:0.5rem">
            <thead><tr><th>Column</th><th>Type</th><th>Nullable</th><th>PK</th></tr></thead>
            <tbody>
              ${cols.map(c => `
                <tr>
                  <td>${c.name}</td>
                  <td>${c.type}</td>
                  <td>${c.nullable ? "Yes" : "No"}</td>
                  <td>${pks.includes(c.name) ? "Yes" : ""}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
          ${(info.foreign_keys || []).length ? `
            <div style="margin-top:0.4rem;font-size:0.8rem;color:var(--muted)">
              FKs: ${(info.foreign_keys||[]).map(fk =>
                `(${(fk.constrained_columns||[]).join(",")}) → ${fk.referred_table}`
              ).join(" · ")}
            </div>
          ` : ""}
        </details>
      `;
    }).join("");
  } catch (e) {
    box.innerHTML = `<p class="status err">${e.message}</p>`;
  }
}

// ---------- Init ----------
refreshConnections();
loadLLMStatus();
