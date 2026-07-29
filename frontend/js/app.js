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

  // 載入初始 Dashboard 資料
  try {
    const data = await fetchDashboard();
    if (data.status === "ok" && data.payload) {
      renderDashboard(data.payload);
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
}

// --- WS 回呼 ---
function onDashboardUpdated(payload) {
  if (payload && payload.kpis) renderDashboard(payload);
}

function onDecisionCompleted(decision) {
  if (!decision) return;
  // 更新 F4 路網圖
  if (decision.routes) updateMap(decision.routes);
  // 更新 F5 報告
  renderReportCard(decision);
  // 更新 F7 決策依據
  renderDecisionBasis(decision);
}

function onRulesEvaluated(sensing) {
  // 可選：更新圖表或 KPI
}

// --- F2 異常彈窗 ---
function showAlertModal(payload) {
  const modal = document.getElementById("f2-alert-modal");
  if (!modal) return;
  const levelColor = payload.level === "A" ? "var(--level-a)" : "var(--level-b)";
  modal.innerHTML = `<div class="alert-content" style="border-color:${levelColor}">
    <h2 style="color:${levelColor}">⚠️ ${payload.level} 級警報</h2>
    <p>${escapeHtml(payload.description || "")}</p>
    ${payload.ete_minutes ? `<p>預計恢復：${payload.ete_minutes} 分鐘</p>` : ""}
    <button onclick="dismissAlert()" style="margin-top:16px;padding:8px 24px;background:${levelColor};color:#fff;border:none;border-radius:6px;cursor:pointer">確認</button>
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

// --- F5 報告卡片 ---
function renderReportCard(decision) {
  const container = document.getElementById("f5-report");
  if (!container) return;
  let html = "";
  if (decision.control_center_report) {
    html += decision.control_center_report;
  } else {
    html += "(報告生成中或已降級)";
  }
  if (decision.notifications && decision.notifications.zh) {
    html += `\n\n【簡訊通知】\n${decision.notifications.zh}`;
  }
  container.textContent = html;
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
  const label = type === "cycle_start" ? "週期開始" : "任務更新";
  feed.insertAdjacentHTML("beforeend",
    `<div style="font-size:0.8rem;padding:4px 0;border-bottom:1px solid #334155">
      <span style="color:#64748b">${time}</span> ${label}: ${escapeHtml(JSON.stringify(payload).slice(0, 80))}
    </div>`
  );
  feed.scrollTop = feed.scrollHeight;
}

function renderDecisionBasis(decision) {
  const panel = document.getElementById("f7-basis-detail");
  if (!panel) return;
  let html = "";
  if (decision.routes && decision.routes.candidates) {
    html += `<div style="margin-bottom:8px"><strong>候選路段評估：</strong></div>`;
    decision.routes.candidates.forEach((c) => {
      const status = c.eligible ? "✓ 合格" : `✗ ${c.reason_code}`;
      html += `<div style="font-size:0.8rem">${c.name} (${c.segment_id}) — ${status}</div>`;
    });
  }
  if (decision.ete) {
    html += `<div style="margin-top:8px"><strong>ETE：</strong>${decision.ete.minutes} 分鐘（${decision.ete.formula}）</div>`;
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
