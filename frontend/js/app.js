/**
 * Dashboard 主邏輯：KPI 渲染 / F7 分頁 / F2 彈窗 / F5 報告卡片 / F3 事件注入。
 * 參考 spec：m5-api-orchestrator-dashboard/design.md 第六節。
 * 資料形狀依 src/models.py 的 DashboardPayload / DecisionResult，不重算任何規則。
 */

// --- 初始化 ---
document.addEventListener("DOMContentLoaded", async () => {
  initChatApp();
  connectWebSocket();
  initCharts();
  initMap();
  initF7Tabs();
  initF3InjectForm();
  initHeaderClock();

  // 載入初始 Dashboard 資料
  try {
    const data = await fetchDashboard();
    if (data.status === "ok" && data.payload) {
      renderDashboard(data.payload);
    }
    if (data.traffic_samples) {
      updateChartData(data.traffic_samples);
    }
  } catch (e) {
    console.warn("初始 Dashboard 載入失敗:", e);
  }
});

// --- F1 KPI ---
function renderKpis(kpis) {
  if (!kpis) return;
  const cards = document.querySelectorAll(".kpi-card");
  const values = [
    { key: "active_incident_count", label: "進行中事件", value: kpis.active_incident_count ?? 0 },
    { key: "current_level", label: "最高應變等級", value: kpis.current_level || "正常" },
    { key: "average_saturation", label: "平均飽和度", value: kpis.average_saturation != null ? (kpis.average_saturation * 100).toFixed(1) + "%" : "N/A" },
    { key: "multilingual_alert_count", label: "多語通報站點", value: kpis.multilingual_alert_count ?? 0 },
    { key: "system_mode", label: "系統模式", value: kpis.system_mode === "live" ? "Live" : "Degraded" },
  ];

  cards.forEach((card, i) => {
    if (values[i]) {
      card.innerHTML = `<div class="kpi-value">${values[i].value}</div><div class="kpi-label">${values[i].label}</div>`;
    }
  });
}

// --- Dashboard 整合渲染 ---
function renderDashboard(payload) {
  renderKpis(payload.kpis);
  // 如果有 active_incidents，顯示在 F3 旁邊或下方
  if (payload.active_incidents && payload.active_incidents.length) {
    renderActiveIncidentsList(payload.active_incidents);
  }
}

function renderActiveIncidentsList(incidents) {
  const inject = document.getElementById("f3-inject");
  if (!inject) return;
  // 在注入按鈕下方加事件狀態列表
  let existing = document.getElementById("active-incidents-list");
  if (!existing) {
    existing = document.createElement("div");
    existing.id = "active-incidents-list";
    existing.style.cssText = "margin-top:12px;padding-top:10px;border-top:1px solid var(--border)";
    inject.appendChild(existing);
  }
  existing.innerHTML = `<div style="font-size:0.65rem;color:var(--muted-foreground);margin-bottom:6px">進行中事件</div>` +
    incidents.map(i => `<div style="font-size:0.73rem;padding:3px 0;color:hsl(0,0%,70%)">${escapeHtml(i.event_id)} · ${escapeHtml(i.location || i.type)}</div>`).join("");
}

// --- WS 回呼 ---
function onDashboardUpdated(payload) {
  if (payload && payload.kpis) renderDashboard(payload);
}

function onDecisionCompleted(decision) {
  if (!decision) return;
  // 更新 F4 路網圖
  if (decision.routes) updateMap(decision.routes);
  // 更新 F5 報告（結構化摘要 + 全文）
  renderReportCard(decision);
  // 更新 F7 決策依據
  renderDecisionBasis(decision);
  // 更新 KPI（事件數）
  const countCard = document.querySelectorAll(".kpi-card")[0];
  if (countCard) {
    const current = parseInt(countCard.querySelector(".kpi-value")?.textContent || "0");
    countCard.innerHTML = `<div class="kpi-value">${current + 1}</div><div class="kpi-label">進行中事件</div>`;
  }
  // 更新等級 KPI
  if (decision.level) {
    const levelCard = document.querySelectorAll(".kpi-card")[1];
    if (levelCard) {
      const color = decision.level === "A" ? "var(--level-a)" : "var(--level-b)";
      levelCard.innerHTML = `<div class="kpi-value" style="color:${color}">${decision.level}</div><div class="kpi-label">最高應變等級</div>`;
    }
  }
}

function onRulesEvaluated(sensing) {
  if (!sensing) return;
  // 更新 KPI：最高應變等級
  const levelCard = document.querySelectorAll(".kpi-card")[1];
  if (levelCard && sensing.traffic_level) {
    const displayLevel = sensing.traffic_level === "normal" ? "正常" : sensing.traffic_level;
    levelCard.innerHTML = `<div class="kpi-value">${displayLevel}</div><div class="kpi-label">最高應變等級</div>`;
  }
  // 更新 KPI：多語通報站點（從 rule_hits 計算 SOP-6 命中數）
  if (sensing.rule_hits) {
    const sop6Count = sensing.rule_hits.filter(h => h.clause_id === "SOP-6").length;
    const multiCard = document.querySelectorAll(".kpi-card")[3];
    if (multiCard) {
      multiCard.innerHTML = `<div class="kpi-value">${sop6Count}</div><div class="kpi-label">多語通報站點</div>`;
    }
  }
}

// --- F2 異常彈窗 ---
function showAlertModal(payload) {
  const modal = document.getElementById("f2-alert-modal");
  if (!modal) return;
  const isA = payload.level === "A";
  const levelLabel = isA ? "A 級警報" : "B 級警報";
  const levelColor = isA ? "hsl(0,84%,60%)" : "hsl(25,95%,53%)";
  modal.innerHTML = `<div class="alert-content">
    <div style="font-size:0.65rem;font-weight:600;letter-spacing:0.05em;color:${levelColor};margin-bottom:12px">${levelLabel}</div>
    <p style="font-size:0.875rem;color:hsl(0,0%,85%);line-height:1.6;margin-bottom:8px">${escapeHtml(payload.description || "")}</p>
    ${payload.ete_minutes ? `<p style="font-size:0.8rem;color:hsl(0,0%,50%)">預計恢復：${payload.ete_minutes} 分鐘</p>` : ""}
    <button onclick="dismissAlert()" style="margin-top:20px;padding:8px 20px;background:hsl(0,0%,95%);color:hsl(0,0%,5%);border:none;border-radius:6px;cursor:pointer;font-size:0.8rem;font-weight:600">確認</button>
  </div>`;
  modal.hidden = false;
}

function dismissAlert() {
  const modal = document.getElementById("f2-alert-modal");
  if (modal) modal.hidden = true;
}

// --- F3 事件注入 ---
function initF3InjectForm() {
  const form = document.getElementById("incident-inject-form");
  if (!form) return;
  const events = [
    { id: "TPE_2026_ACC_001", label: "路面塌陷（光復南路）" },
    { id: "TPE_2026_EVT_002", label: "人群推擠（國父紀念館站）" },
    { id: "TPE_2026_EVT_003", label: "號誌故障（松高路）" },
  ];
  form.innerHTML = events.map(e =>
    `<button type="button" onclick="injectIncident('${e.id}')">${e.label}</button>`
  ).join("");
}

async function injectIncident(eventId) {
  try {
    const data = await fetchEvaluateIncident(eventId);
    if (data.status === "ok" && data.payload) {
      onDecisionCompleted(data.payload);
    }
  } catch (e) {
    console.warn("事件注入失敗:", e);
  }
}

// --- F5 報告卡片（結構化摘要 + 全文） ---
function renderReportCard(decision) {
  const container = document.getElementById("f5-report-content");
  if (!container) return;

  let html = "";

  // 結構化摘要
  html += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--border)">`;

  // 左欄：事件資訊
  html += `<div>`;
  if (decision.incident) {
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:4px">EVENT</div>`;
    html += `<div style="font-size:0.85rem;font-weight:600;color:var(--text)">${escapeHtml(decision.incident.description || decision.incident.type)}</div>`;
    html += `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:3px">${escapeHtml(decision.incident.location || "")}</div>`;
  }
  if (decision.level) {
    const lColor = decision.level === "A" ? "var(--level-a)" : "var(--level-b)";
    html += `<div style="margin-top:8px;display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.65rem;font-weight:600;color:${lColor};border:1px solid ${lColor}">${decision.level} 級</div>`;
  }
  html += `</div>`;

  // 右欄：路線 + ETE
  html += `<div>`;
  if (decision.ete) {
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:4px">ETE</div>`;
    html += `<div style="font-size:1.4rem;font-weight:700;color:var(--text);letter-spacing:-0.03em">${decision.ete.minutes} <span style="font-size:0.7rem;font-weight:400;color:var(--text-muted)">min</span></div>`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-top:2px;font-variant-numeric:tabular-nums">${escapeHtml(decision.ete.formula || "")}</div>`;
  }
  if (decision.routes) {
    html += `<div style="margin-top:10px;font-size:0.72rem;display:flex;flex-direction:column;gap:2px">`;
    if (decision.routes.primary) html += `<div><span style="color:hsl(142,71%,45%)">●</span> ${escapeHtml(decision.routes.primary.name)}</div>`;
    if (decision.routes.secondary) html += `<div><span style="color:hsl(48,96%,53%)">●</span> ${escapeHtml(decision.routes.secondary.name)}</div>`;
    html += `</div>`;
  }
  html += `</div>`;
  html += `</div>`;

  // 多語簡訊
  if (decision.notifications) {
    html += `<div style="margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid var(--border)">`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">NOTIFICATIONS</div>`;
    const n = decision.notifications;
    if (n.zh) html += `<div style="font-size:0.72rem;margin-bottom:3px;color:var(--text-secondary)"><span style="color:var(--text-muted);font-size:0.6rem;margin-right:6px">ZH</span>${escapeHtml(n.zh)}</div>`;
    if (n.en) html += `<div style="font-size:0.72rem;margin-bottom:3px;color:var(--text-secondary)"><span style="color:var(--text-muted);font-size:0.6rem;margin-right:6px">EN</span>${escapeHtml(n.en)}</div>`;
    if (n.ja) html += `<div style="font-size:0.72rem;margin-bottom:3px;color:var(--text-secondary)"><span style="color:var(--text-muted);font-size:0.6rem;margin-right:6px">JA</span>${escapeHtml(n.ja)}</div>`;
    if (n.ko) html += `<div style="font-size:0.72rem;margin-bottom:3px;color:var(--text-secondary)"><span style="color:var(--text-muted);font-size:0.6rem;margin-right:6px">KO</span>${escapeHtml(n.ko)}</div>`;
    html += `</div>`;
  }

  // 建議書全文
  if (decision.control_center_report) {
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">FULL REPORT</div>`;
    html += `<div style="font-size:0.75rem;line-height:1.7;color:var(--text-secondary);white-space:pre-wrap">${escapeHtml(decision.control_center_report)}</div>`;
  }

  // 元資訊
  html += `<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border);font-size:0.62rem;color:var(--text-muted);display:flex;gap:16px;font-variant-numeric:tabular-nums">`;
  html += `<span>${decision.trace_id || "—"}</span>`;
  html += `<span>${decision.duration_ms || 0}ms</span>`;
  if (decision.degraded && decision.degraded.length) html += `<span style="color:var(--level-b)">${decision.degraded.join(", ")}</span>`;
  html += `</div>`;

  container.innerHTML = html;
}

// --- F7 決策依據分頁 ---
function initF7Tabs() {
  const buttons = document.querySelectorAll(".f7-tabs button");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("f7-activity-feed").hidden = tab !== "activity";
      document.getElementById("f7-basis-detail").hidden = tab !== "basis";
    });
  });
  // 預設顯示即時活動
  if (buttons[0]) buttons[0].classList.add("active");
}

function appendActivityEntry(type, payload) {
  const feed = document.getElementById("f7-activity-feed");
  if (!feed) return;
  const time = formatTime(new Date().toISOString());

  let label, detail, color;
  if (type === "cycle_start") {
    label = "決策週期啟動";
    detail = payload.triggered_by ? `觸發：${payload.triggered_by.join(", ")}` : "";
    color = "hsl(0,0%,60%)";
  } else {
    const statusMap = {
      "routing_started": ["路網規劃", "計算中...", "hsl(142,71%,45%)"],
      "routing_done": ["路網規劃", "完成", "hsl(142,71%,45%)"],
      "ete_started": ["ETE 計算", "計算中...", "hsl(48,96%,53%)"],
      "ete_done": ["ETE 計算", "完成", "hsl(48,96%,53%)"],
      "report_started": ["報告生成", "生成中...", "hsl(270,50%,60%)"],
      "report_done": ["報告生成", "完成", "hsl(270,50%,60%)"],
    };
    const [lbl, det, clr] = statusMap[payload.status] || ["任務", payload.status, "hsl(0,0%,50%)"];
    label = lbl;
    detail = det;
    color = clr;
  }

  feed.insertAdjacentHTML("beforeend",
    `<div style="font-size:0.72rem;padding:5px 0;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px">
      <span style="color:var(--text-muted);min-width:42px;font-variant-numeric:tabular-nums;font-size:0.65rem">${time}</span>
      <span style="color:${color};font-weight:500">${label}</span>
      <span style="color:var(--text-muted);font-size:0.68rem">${detail}</span>
    </div>`
  );
  feed.scrollTop = feed.scrollHeight;
}

function renderDecisionBasis(decision) {
  const panel = document.getElementById("f7-basis-detail");
  if (!panel) return;
  let html = "";

  // 觸發的 SOP
  if (decision.triggered_by && decision.triggered_by.length) {
    html += `<div style="margin-bottom:12px">`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">TRIGGERED</div>`;
    html += decision.triggered_by.map(t => `<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.68rem;background:var(--bg-elevated);border:1px solid var(--border);margin-right:4px;color:var(--text-secondary)">${t}</span>`).join("");
    html += `</div>`;
  }

  // 候選路段評估
  if (decision.routes) {
    html += `<div style="margin-bottom:12px">`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">ROUTE PLAN</div>`;
    if (decision.routes.primary) {
      html += `<div style="font-size:0.73rem;margin-bottom:4px;color:var(--text-secondary)"><span style="color:hsl(142,71%,45%)">●</span> <strong style="color:var(--text)">Primary</strong> ${escapeHtml(decision.routes.primary.name)} — ${(decision.routes.primary.saturation_score * 100).toFixed(0)}% · ${decision.routes.primary.capacity_vph} vph</div>`;
    }
    if (decision.routes.secondary) {
      html += `<div style="font-size:0.73rem;margin-bottom:4px;color:var(--text-secondary)"><span style="color:hsl(48,96%,53%)">●</span> <strong style="color:var(--text)">Secondary</strong> ${escapeHtml(decision.routes.secondary.name)} — ${(decision.routes.secondary.saturation_score * 100).toFixed(0)}% · ${decision.routes.secondary.capacity_vph} vph</div>`;
    }
    if (decision.routes.excluded && decision.routes.excluded.length) {
      html += `<div style="margin-top:8px;font-size:0.65rem;color:var(--text-muted);margin-bottom:4px">EXCLUDED</div>`;
      decision.routes.excluded.forEach((e) => {
        html += `<div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:2px">✗ ${escapeHtml(e.name)} — <code style="font-size:0.63rem;background:var(--bg-elevated);padding:1px 4px;border-radius:3px">${e.reason_code}</code></div>`;
      });
    }
    if (decision.routes.duration_ms !== undefined) {
      const slaOk = decision.routes.within_60_second_sla;
      html += `<div style="margin-top:6px;font-size:0.65rem;color:${slaOk ? 'var(--success)' : 'var(--level-a)'}">${decision.routes.duration_ms}ms ${slaOk ? '✓' : '✗ SLA exceeded'}</div>`;
    }
    html += `</div>`;
  }

  // ETE 公式
  if (decision.ete) {
    html += `<div>`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:4px">ETE</div>`;
    html += `<div style="font-size:0.85rem;font-weight:600;color:var(--text)">${decision.ete.minutes} min</div>`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);font-variant-numeric:tabular-nums">${escapeHtml(decision.ete.formula || "")}</div>`;
    if (decision.ete.recovery_at) html += `<div style="font-size:0.65rem;color:var(--text-muted)">Recovery: ${decision.ete.recovery_at}</div>`;
    html += `</div>`;
  }

  panel.innerHTML = html;
}

function updateStatusBanner(payload) {
  const banner = document.getElementById("status-banner");
  if (!banner) return;
  if (payload.level) {
    banner.className = `chat-status-banner visible level-${payload.level.toLowerCase()}`;
    banner.textContent = `目前應變等級：${payload.level}`;
  } else {
    banner.className = "chat-status-banner";
  }
}

// --- Header Clock ---
function initHeaderClock() {
  const el = document.getElementById("header-time");
  if (!el) return;
  function tick() {
    const now = new Date();
    el.textContent = now.toLocaleTimeString("zh-TW", { hour12: false });
  }
  tick();
  setInterval(tick, 1000);
}
