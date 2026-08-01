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
  initExpandReportBtn();
  initSideNav();
  initPageNav();
  initSimulation();

  // 載入初始 Dashboard 資料
  try {
    const data = await fetchDashboard();
    if (data.status === "ok" && data.payload) {
      renderDashboard(data.payload);
    }
    if (data.traffic_samples) {
      updateChartData(data.traffic_samples);
      // 更新飽和地圖（顯示各路段即時狀態），但不自動加入警報列表
      if (typeof updateSaturationFromSamples === "function") {
        updateSaturationFromSamples(data.traffic_samples);
      }
    }
  } catch (e) {
    console.warn("初始 Dashboard 載入失敗:", e);
  }
  
  // 初始化飽和地圖（空白狀態）
  setTimeout(() => {
    if (typeof initSaturationMap === "function") {
      initSaturationMap();
    }
    // 同時初始化 Dashboard 飽和列表
    if (typeof renderDashboardSaturationList === "function") {
      renderDashboardSaturationList();
    }
  }, 500);
});

// --- 頁面切換 ---
function initPageNav() {
  // 頁面切換已在 HTML onclick 處理，這裡可加額外初始化邏輯
}

function setSideNavCollapsed(collapsed) {
  const sidebar = document.querySelector(".side-nav-shell");
  const toggle = document.querySelector(".side-nav-toggle");
  if (!sidebar || !toggle) return;

  sidebar.classList.toggle("collapsed", collapsed);
  document.body.classList.toggle("side-nav-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", collapsed ? "展開側邊欄" : "收縮側邊欄");
  toggle.title = collapsed ? "展開側邊欄" : "收縮側邊欄";
}

function initSideNav() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem("citynexus-side-nav-collapsed") === "true";
  } catch (e) {
    console.warn("無法讀取側邊欄偏好:", e);
  }
  setSideNavCollapsed(collapsed);
}

function toggleSideNav() {
  const sidebar = document.querySelector(".side-nav-shell");
  if (!sidebar) return;
  const collapsed = !sidebar.classList.contains("collapsed");
  setSideNavCollapsed(collapsed);
  try {
    localStorage.setItem("citynexus-side-nav-collapsed", String(collapsed));
  } catch (e) {
    console.warn("無法儲存側邊欄偏好:", e);
  }
}

function switchPage(pageName) {
  // 更新導航按鈕狀態
  document.querySelectorAll(".page-nav-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.page === pageName);
  });
  
  // 切換頁面內容
  document.querySelectorAll(".page-content").forEach(page => {
    page.hidden = page.id !== `page-${pageName}`;
  });
  
  // 切換到飽和地圖頁面時，重新渲染（確保資料最新）
  if (pageName === "saturation" && typeof renderSaturationMap === "function") {
    renderSaturationMap();
    renderSaturationList();
  }
}

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
const _processedTraceIds = new Set();

function onDashboardUpdated(payload) {
  if (payload && payload.kpis) renderDashboard(payload);
}

function onDecisionCompleted(decision) {
  if (!decision) return;
  // 用 trace_id 去重（REST 回應 + WS 推播會各呼叫一次，避免重複計數）
  if (decision.trace_id && _processedTraceIds.has(decision.trace_id)) return;
  if (decision.trace_id) _processedTraceIds.add(decision.trace_id);

  if (typeof updateTrafficChartForIncident === "function") {
    updateTrafficChartForIncident(decision);
  }
  
  // 記錄到 Activity Log
  _recordDecisionForActivity(decision);
  
  // 更新 F4 路網圖（傳入事件發生的路段 ID）
  if (decision.routes) {
    const incidentSegmentId = decision.incident?.affected_segment || decision.incident?.affected_road || null;
    updateMap(decision.routes, incidentSegmentId);
  }
  
  // 飽和地圖更新由 decision.alert.v1 負責，不在這裡處理
  
  // 更新 F5 報告（結構化摘要 + 全文）
  renderReportCard(decision);
  // 更新 F7 決策依據
  renderDecisionBasis(decision);
  // 將事件加入對應等級的框
  addIncidentToLevelBox(decision);
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

// --- F2 事件分類到對應等級框 ---
function toggleIncidentBox(level) {
  const box = document.getElementById(`incident-box-${level}`);
  if (box) {
    box.classList.toggle("collapsed");
  }
}

// --- F3 事件注入面板展開/收起 ---
function toggleInjectPanel() {
  const panel = document.getElementById("f3-inject");
  if (panel) {
    panel.classList.toggle("collapsed");
  }
}

function updateIncidentCount(level) {
  const list = document.getElementById(`incident-list-${level}`);
  const countEl = document.getElementById(`incident-count-${level}`);
  const previewEl = document.getElementById(`incident-preview-${level}`);
  
  if (!list || !countEl) return;
  
  const count = list.querySelectorAll(".incident-item").length;
  countEl.textContent = `(${count})`;
  
  // 更新預覽文字
  if (previewEl) {
    if (count === 0) {
      previewEl.textContent = "無事件";
    } else {
      const lastItem = list.querySelector(".incident-item:last-child");
      const title = lastItem?.querySelector(".incident-item-title")?.textContent || "";
      previewEl.textContent = count === 1 ? title : `${title} 等 ${count} 筆`;
    }
  }
}

function addIncidentToLevelBox(decision) {
  console.log("[addIncidentToLevelBox] 收到 decision:", decision);
  console.log("[addIncidentToLevelBox] decision.level:", decision?.level);
  
  if (!decision || !decision.level) {
    console.log("[addIncidentToLevelBox] 跳過：decision 或 level 為空");
    return;
  }
  
  const level = decision.level.toLowerCase();
  console.log("[addIncidentToLevelBox] 處理等級:", level);
  const listId = `incident-list-${level}`;
  const list = document.getElementById(listId);
  if (!list) return;
  
  const eventId = decision.incident?.event_id || decision.trace_id;
  // 檢查是否已存在（避免重複）
  if (list.querySelector(`[data-event-id="${eventId}"]`)) return;
  
  const title = decision.incident?.description || decision.incident?.type || "未知事件";
  const location = decision.incident?.location || "";
  const eteMinutes = decision.ete?.minutes;
  const recoveryAt = decision.ete?.recovery_at;
  
  // ★ 添加 onclick 事件，點擊時切換地圖和報告
  const itemHtml = `
    <div class="incident-item" data-event-id="${escapeHtml(eventId)}" onclick="selectIncidentFromList('${escapeHtml(eventId)}')" style="cursor:pointer;">
      <div class="incident-item-title">${escapeHtml(title)}</div>
      ${location ? `<div class="incident-item-location">${escapeHtml(location)}</div>` : ""}
      ${eteMinutes ? `<div class="incident-item-ete">ETE: <strong>${eteMinutes}</strong> 分鐘${recoveryAt ? ` · 預計 ${escapeHtml(recoveryAt)}` : ""}</div>` : ""}
    </div>
  `;
  
  list.insertAdjacentHTML("beforeend", itemHtml);
  
  // 更新計數和預覽
  updateIncidentCount(level);
}

// ★ 新函式：點擊事件列表項目時切換地圖和報告
function selectIncidentFromList(eventId) {
  console.log(`[selectIncidentFromList] 點擊事件: ${eventId}`);
  
  // 切換 report tab
  if (_allDecisions.has(eventId)) {
    const decision = _allDecisions.get(eventId);
    switchReportTab(eventId);
    if (typeof updateTrafficChartForIncident === "function") {
      updateTrafficChartForIncident(decision);
    }
  }
  
  // 切換 Activity 面板
  if (_activityByEvent.has(eventId)) {
    selectActivityEvent(eventId);
  }
  
  // 更新視覺選中狀態
  document.querySelectorAll(".incident-item").forEach(item => {
    item.classList.toggle("selected", item.dataset.eventId === eventId);
  });
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
  
  // 更新飽和地圖資料（從 segment_snapshots 或 traffic_samples）
  if (sensing.segment_snapshots && typeof updateSaturationFromSamples === "function") {
    updateSaturationFromSamples(sensing.segment_snapshots);
  } else if (sensing.traffic_samples && typeof updateSaturationFromSamples === "function") {
    updateSaturationFromSamples(sensing.traffic_samples);
  }
}

// --- F2 異常彈窗（堆疊式通知）---
let alertCounter = 0;

// 追蹤每個 alert 的自動關閉 timer（以便在手動關閉時清除）
const _alertTimers = new Map();

function showAlertModal(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const isA = payload.level === "A";
  const levelLabel = isA ? "A 級警報" : "B 級警報";
  const levelClass = isA ? "level-a" : "level-b";
  
  const alertId = `alert-${++alertCounter}`;
  
  // 判斷是「事件注入」還是「模擬器路段預警」
  // ete_minutes 為實際數字時是事件注入，null/undefined 且有 road_name 是路段預警
  const isIncidentAlert = (payload.ete_minutes != null) || !payload.road_name;
  // 只有飽和路段預警才自動消失
  const isSaturationAlert = !isIncidentAlert;
  
  let roadName, description, extraInfo;
  
  if (isIncidentAlert) {
    // 事件注入的彈窗
    roadName = "事件通報";
    description = payload.description || "決策完成";
    extraInfo = payload.ete_minutes ? `預計恢復時間：${payload.ete_minutes} 分鐘` : "";
  } else {
    // 模擬器路段飽和度預警
    roadName = payload.road_name || "未知路段";
    const satPercent = payload.saturation ? `${(payload.saturation * 100).toFixed(0)}%` : "";
    description = `飽和度：${satPercent}`;
    extraInfo = "";
    
    // 新增到飽和警報列表並更新地圖（addSaturationAlert 會處理所有頁面的更新）
    if (payload.segment_id && payload.saturation !== undefined) {
      if (typeof addSaturationAlert === "function") {
        addSaturationAlert(payload.segment_id, payload.road_name, payload.saturation, payload.timestamp);
      }
    }
  }
  
  const timeStr = payload.description?.match(/\[(\d+:\d+)\]/)?.[1] || "";
  
  const alertEl = document.createElement("div");
  alertEl.className = `alert-item ${levelClass}`;
  alertEl.id = alertId;
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level">${levelLabel}</span>
      <span class="alert-item-time">${timeStr}</span>
    </div>
    <div class="alert-item-road">${escapeHtml(roadName)}</div>
    <div class="alert-item-desc">${escapeHtml(description)}</div>
    ${extraInfo ? `<div class="alert-item-extra">${escapeHtml(extraInfo)}</div>` : ""}
    ${isSaturationAlert ? '<div class="alert-item-progress"><div class="alert-item-progress-bar"></div></div>' : ""}
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')">確認</button>
  `;
  
  stack.appendChild(alertEl);
  
  // 只有飽和路段預警才 4 秒後自動關閉
  if (isSaturationAlert) {
    const autoCloseTimer = setTimeout(() => {
      dismissAlertItem(alertId);
    }, 4000);
    
    // 記錄 timer，以便手動關閉時清除
    _alertTimers.set(alertId, autoCloseTimer);
  }
}

function dismissAlertItem(alertId) {
  // 清除自動關閉的 timer（如果存在）
  if (_alertTimers.has(alertId)) {
    clearTimeout(_alertTimers.get(alertId));
    _alertTimers.delete(alertId);
  }
  
  const alertEl = document.getElementById(alertId);
  if (alertEl) {
    alertEl.style.animation = "alertSlideIn 0.2s ease-out reverse";
    setTimeout(() => alertEl.remove(), 200);
  }
}

function dismissAlert() {
  const modal = document.getElementById("f2-alert-modal");
  if (modal) modal.hidden = true;
}

// --- F3 事件注入 ---
// 全域變數：儲存從後端載入的事件列表
let _availableIncidents = [];

async function initF3InjectForm() {
  const form = document.getElementById("incident-inject-form");
  if (!form) {
    console.error("[initF3InjectForm] 找不到 #incident-inject-form");
    return;
  }

  console.log("[initF3InjectForm] 開始載入事件列表...");
  
  // 顯示載入中狀態
  form.innerHTML = `<div style="font-size:0.72rem;color:var(--text-muted);padding:8px 0;">載入事件列表中...</div>`;

  // 從後端載入事件列表
  try {
    const data = await fetchIncidents();
    console.log("[initF3InjectForm] API 回應:", data);
    
    if (data.status === "ok" && data.incidents) {
      _availableIncidents = data.incidents;
      console.log(`[initF3InjectForm] 載入 ${_availableIncidents.length} 筆事件`);
      renderIncidentButtons(form);
    } else {
      console.error("[initF3InjectForm] API 回應錯誤:", data);
      form.innerHTML = `<div style="font-size:0.72rem;color:var(--level-a);">載入失敗: ${JSON.stringify(data)}</div>`;
    }
  } catch (e) {
    console.error("載入事件列表失敗:", e);
    // 失敗時顯示預設的三個事件
    _availableIncidents = [
      { event_id: "TPE_2026_ACC_001", type: "Road_Collapse_Accident", location: "光復南路", severity: "Critical" },
      { event_id: "TPE_2026_EVT_002", type: "Crowd_Surge_Injury", location: "國父紀念館站", severity: "High" },
      { event_id: "TPE_2026_EVT_003", type: "Power_Failure", location: "松高路", severity: "Medium" },
    ];
    renderIncidentButtons(form);
  }
}

function renderIncidentButtons(form) {
  if (!form) {
    console.error("[renderIncidentButtons] form 為 null");
    return;
  }

  console.log(`[renderIncidentButtons] 渲染 ${_availableIncidents.length} 筆事件`);

  // 依嚴重度分組
  const critical = _availableIncidents.filter(e => e.severity === "Critical");
  const high = _availableIncidents.filter(e => e.severity === "High");
  const medium = _availableIncidents.filter(e => e.severity === "Medium");
  const low = _availableIncidents.filter(e => e.severity === "Low");

  console.log(`[renderIncidentButtons] Critical: ${critical.length}, High: ${high.length}, Medium: ${medium.length}, Low: ${low.length}`);

  // 產生事件按鈕的 HTML
  function makeButton(e) {
    const shortType = _getShortType(e.type);
    const shortLocation = e.location?.length > 12 ? e.location.substring(0, 12) + "…" : (e.location || "");
    const isInjected = _injectedEventIds.has(e.event_id);
    const disabledAttr = isInjected ? 'disabled style="opacity:0.5;cursor:not-allowed;"' : '';
    const checkMark = isInjected ? ' ✓' : '';
    return `<button type="button" onclick="injectIncident('${escapeHtml(e.event_id)}')" ${disabledAttr} title="${escapeHtml(e.event_id)}\n${escapeHtml(e.description || '')}">${shortType}（${shortLocation}）${checkMark}</button>`;
  }

  let html = '';

  // Critical 事件（紅色區塊）
  if (critical.length > 0) {
    html += `<div class="inject-group critical">
      <div class="inject-group-header"><span class="severity-dot critical"></span>Critical (${critical.length})</div>
      <div class="inject-group-buttons">${critical.map(makeButton).join('')}</div>
    </div>`;
  }

  // High 事件（橘色區塊）
  if (high.length > 0) {
    html += `<div class="inject-group high">
      <div class="inject-group-header"><span class="severity-dot high"></span>High (${high.length})</div>
      <div class="inject-group-buttons">${high.map(makeButton).join('')}</div>
    </div>`;
  }

  // Medium 事件（黃色區塊）
  if (medium.length > 0) {
    html += `<div class="inject-group medium">
      <div class="inject-group-header"><span class="severity-dot medium"></span>Medium (${medium.length})</div>
      <div class="inject-group-buttons">${medium.map(makeButton).join('')}</div>
    </div>`;
  }

  // Low 事件（綠色區塊）
  if (low.length > 0) {
    html += `<div class="inject-group low">
      <div class="inject-group-header"><span class="severity-dot low"></span>Low (${low.length})</div>
      <div class="inject-group-buttons">${low.map(makeButton).join('')}</div>
    </div>`;
  }

  // 模擬事件區塊
  html += `
    <div style="margin:12px 0 8px;padding-top:10px;border-top:1px solid var(--border);font-size:0.65rem;color:var(--text-muted);">模擬事件</div>
    <button type="button" onclick="generateRandomIncident()" style="background:linear-gradient(135deg, hsl(200,70%,40%), hsl(260,70%,50%));color:white;border:none;">🎲 模擬隨機事件</button>
    <button type="button" onclick="reloadIncidentList()" style="margin-top:4px;background:transparent;color:var(--text-muted);border-color:var(--border);">🔄 重新載入事件列表</button>
  `;

  form.innerHTML = html;
}

// 重新載入事件列表
async function reloadIncidentList() {
  _injectedEventIds.clear();  // 清除已注入標記
  await initF3InjectForm();
}

// 將事件類型轉換為簡短顯示名稱
function _getShortType(type) {
  const typeMap = {
    "Road_Collapse_Accident": "路面塌陷",
    "Traffic_Accident": "車禍",
    "Crowd_Surge_Injury": "人群推擠",
    "Power_Failure": "號誌故障",
    "Vehicle_Fire": "車輛起火",
    "Large_Event_Dispersal": "大型散場",
    "Water_Main_Break": "水管破裂",
    "Debris_On_Road": "路面障礙",
  };
  return typeMap[type] || type;
}

// 生成隨機事件
async function generateRandomIncident() {
  try {
    const res = await fetch("/api/incidents/generate", { method: "POST" });
    const data = await res.json();
    if (data.status === "ok" && data.payload) {
      const decision = data.payload;
      onDecisionCompleted(decision);
      // 彈窗由 WebSocket decision.alert.v1 推播觸發，這裡不重複呼叫
    } else if (data.errors) {
      console.warn("生成事件失敗:", data.errors);
    }
  } catch (e) {
    console.warn("生成事件失敗:", e);
  }
}

// 重設系統狀態
async function resetSystem() {
  if (!confirm("確定要重設系統？這會清空所有進行中的事件。")) return;
  
  console.log("[resetSystem] 開始重設...");
  console.log("[resetSystem] 重設前 _activityByEvent.size =", _activityByEvent.size);
  
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    const data = await res.json();
    console.log("[resetSystem] 後端回應:", data);
    
    if (data.status === "ok") {
      // 清空前端狀態（使用多種方式確保徹底清空）
      _injectedEventIds.clear();
      _allDecisions.clear();
      _activityByEvent.clear();
      _processedTraceIds.clear();
      _currentEventId = null;
      _selectedActivityEventId = null;
      _lastInjectedEventId = null;
      
      console.log("[resetSystem] 清空後 _activityByEvent.size =", _activityByEvent.size);
      
      // 清空飽和地圖資料
      if (typeof clearSaturationData === "function") {
        clearSaturationData();
      }
      
      // 重新載入 Dashboard
      const dashData = await fetchDashboard();
      if (dashData.status === "ok" && dashData.payload) {
        renderDashboard(dashData.payload);
      }
      
      // 重新初始化注入表單（恢復按鈕狀態）
      initF3InjectForm();
      
      // 清空各區域 DOM
      document.getElementById("f5-report-content").innerHTML = "";
      document.getElementById("f7-activity-feed").innerHTML = "";
      document.getElementById("f7-basis-detail").innerHTML = "";
      document.getElementById("incident-list-a").innerHTML = "";
      document.getElementById("incident-list-b").innerHTML = "";
      
      // 強制清空 Activity 事件列表 DOM
      const activityEventList = document.getElementById("activity-event-list");
      if (activityEventList) {
        activityEventList.innerHTML = '<div class="activity-empty">尚無事件紀錄</div>';
        console.log("[resetSystem] 已清空 activity-event-list DOM");
      }
      
      // 清空報告 tabs
      const reportTabs = document.getElementById("f5-report-tabs");
      if (reportTabs) reportTabs.innerHTML = "";
      
      // 隱藏 Activity tabs
      const activityTabs = document.getElementById("activity-tabs");
      if (activityTabs) activityTabs.hidden = true;
      
      // 重設 Activity header
      const activityHeader = document.getElementById("activity-main-header");
      if (activityHeader) activityHeader.textContent = "選擇事件查看詳情";
      
      // 更新計數
      updateIncidentCount("a");
      updateIncidentCount("b");
      
      console.log("[resetSystem] 系統重設完成，最終 _activityByEvent.size =", _activityByEvent.size);
      alert("系統已重設");
    } else {
      console.warn("[resetSystem] 後端回應非 ok:", data);
      alert("重設失敗：" + (data.message || "未知錯誤"));
    }
  } catch (e) {
    console.error("[resetSystem] 重設失敗:", e);
    alert("重設失敗");
  }
}

// 追蹤已注入的事件（避免重複注入）
const _injectedEventIds = new Set();

async function injectIncident(eventId) {
  // 檢查是否已注入過
  if (_injectedEventIds.has(eventId)) {
    console.log(`事件 ${eventId} 已注入，跳過重複請求`);
    return;
  }
  
  try {
    _lastInjectedEventId = eventId; // 記錄當前注入的事件
    _injectedEventIds.add(eventId); // 標記為已注入
    
    // 禁用該按鈕
    const btn = document.querySelector(`button[onclick="injectIncident('${eventId}')"]`);
    if (btn) {
      btn.disabled = true;
      btn.style.opacity = "0.5";
      btn.style.cursor = "not-allowed";
      btn.textContent = btn.textContent + " ✓";
    }
    
    console.log(`[injectIncident] 開始注入事件: ${eventId}`);
    const data = await fetchEvaluateIncident(eventId);
    console.log(`[injectIncident] API 回應:`, data);
    
    if (data.status === "ok" && data.payload) {
      const decision = data.payload;
      console.log(`[injectIncident] decision.routes:`, decision.routes);
      
      onDecisionCompleted(decision);
      
      // ★ 確保地圖立即更新（傳入事件發生的路段 ID）
      if (decision.routes) {
        const incidentSegmentId = decision.incident?.affected_segment || decision.incident?.affected_road || null;
        console.log(`[injectIncident] 直接呼叫 updateMap, 事件路段: ${incidentSegmentId}`);
        updateMap(decision.routes, incidentSegmentId);
      }
      // 彈窗由 WebSocket decision.alert.v1 推播觸發，這裡不重複呼叫
    }
  } catch (e) {
    console.warn("事件注入失敗:", e);
    // 注入失敗時移除標記，允許重試
    _injectedEventIds.delete(eventId);
  }
}

// --- F5 報告卡片（結構化摘要 + 全文） ---
const _allDecisions = new Map(); // key=event_id, value=decision
let _currentEventId = null; // 目前顯示的事件

function renderReportCard(decision) {
  const container = document.getElementById("f5-report-content");
  if (!container) return;

  // 存入 Map（用 event_id 作為 key）
  const eventId = decision.incident?.event_id || decision.trace_id;
  _allDecisions.set(eventId, decision);
  _currentEventId = eventId;

  // 更新事件切換 tabs
  _renderReportTabs();

  // 渲染報告內容
  _renderReportContent(decision);
}

// 渲染報告內容（抽出成獨立函式）
function _renderReportContent(decision) {
  const container = document.getElementById("f5-report-content");
  if (!container) return;

  // 啟用放大按鈕
  const expandBtn = document.getElementById("expand-report-btn");
  if (expandBtn) expandBtn.disabled = false;

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
    if (decision.routes.primary) {
      const isChanged = decision.routes.primary._changedAt;
      const changeNote = isChanged ? ` <span style="font-size:0.6rem;color:hsl(38,92%,50%)">(已更新)</span>` : "";
      html += `<div><span style="color:hsl(142,71%,45%)">●</span> ${escapeHtml(decision.routes.primary.name)}${changeNote}</div>`;
    }
    if (decision.routes.secondary) {
      const isChanged = decision.routes.secondary._changedAt;
      const changeNote = isChanged ? ` <span style="font-size:0.6rem;color:hsl(38,92%,50%)">(已更新)</span>` : "";
      html += `<div><span style="color:hsl(48,96%,53%)">●</span> ${escapeHtml(decision.routes.secondary.name)}${changeNote}</div>`;
    }
    html += `</div>`;
  }
  html += `</div>`;
  html += `</div>`;

  // 路線變更歷史（如果有）
  if (decision._routeHistory && decision._routeHistory.length > 0) {
    html += `<div style="margin-bottom:14px;padding:10px;background:rgba(255,150,50,0.08);border:1px solid hsl(38,92%,50%,0.3);border-radius:6px">`;
    html += `<div style="font-size:0.65rem;color:hsl(38,92%,50%);margin-bottom:8px;font-weight:600">🔄 ROUTE CHANGE HISTORY</div>`;
    
    decision._routeHistory.forEach((change, idx) => {
      const time = change.time ? new Date(change.time).toLocaleTimeString("zh-TW", {hour: "2-digit", minute: "2-digit"}) : "";
      const oldName = _getSegmentName(change.oldPrimary) || change.oldPrimary;
      const newName = _getSegmentName(change.newPrimary) || change.newPrimary;
      
      html += `<div style="font-size:0.72rem;${idx > 0 ? 'margin-top:8px;padding-top:8px;border-top:1px solid hsl(38,92%,50%,0.2);' : ''}">`;
      html += `<div style="display:flex;justify-content:space-between;margin-bottom:3px">`;
      html += `<span style="color:var(--text-secondary)">第 ${idx + 1} 次重規劃</span>`;
      html += `<span style="color:var(--text-muted);font-size:0.65rem">${time}</span>`;
      html += `</div>`;
      html += `<div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:2px">原因: ${escapeHtml(change.reason)}</div>`;
      html += `<div style="font-size:0.7rem">`;
      html += `<span style="color:hsl(0,70%,60%)">✗ ${escapeHtml(oldName)}</span>`;
      html += ` → `;
      html += `<span style="color:hsl(142,71%,45%)">✓ ${escapeHtml(newName)}</span>`;
      html += `</div>`;
      html += `</div>`;
    });
    
    html += `</div>`;
  }

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

// 渲染事件切換 tabs
function _renderReportTabs() {
  const section = document.getElementById("f5-report");
  if (!section) return;

  let tabsContainer = document.getElementById("f5-report-tabs");
  if (!tabsContainer) {
    tabsContainer = document.createElement("div");
    tabsContainer.id = "f5-report-tabs";
    tabsContainer.style.cssText = "display:flex;gap:4px;padding:8px 12px;border-bottom:1px solid var(--border);overflow-x:auto;flex-wrap:nowrap;";
    // 插入到 section-header 之後
    const header = section.querySelector(".section-header");
    if (header && header.nextSibling) {
      section.insertBefore(tabsContainer, header.nextSibling);
    } else {
      section.insertBefore(tabsContainer, section.firstChild.nextSibling);
    }
  }

  // 建立 tabs
  let tabsHtml = "";
  for (const [eventId, dec] of _allDecisions) {
    const isActive = eventId === _currentEventId;
    const label = dec.incident?.description || dec.incident?.type || eventId;
    const shortLabel = label.length > 12 ? label.substring(0, 12) + "…" : label;
    const levelColor = dec.level === "A" ? "var(--level-a)" : dec.level === "B" ? "var(--level-b)" : "var(--text-muted)";
    tabsHtml += `<button 
      onclick="switchReportTab('${escapeHtml(eventId)}')" 
      style="padding:4px 10px;border-radius:4px;font-size:0.68rem;border:1px solid ${isActive ? levelColor : 'var(--border)'};
             background:${isActive ? 'var(--bg-elevated)' : 'transparent'};color:${isActive ? levelColor : 'var(--text-muted)'};
             cursor:pointer;white-space:nowrap;transition:all 0.15s;"
      title="${escapeHtml(label)}"
    >${shortLabel}</button>`;
  }
  tabsContainer.innerHTML = tabsHtml;

  // 如果只有一個事件，隱藏 tabs
  tabsContainer.style.display = _allDecisions.size <= 1 ? "none" : "flex";
}

// 切換報告 tab
function switchReportTab(eventId) {
  if (!_allDecisions.has(eventId)) return;
  _currentEventId = eventId;
  const decision = _allDecisions.get(eventId);
  if (typeof updateTrafficChartForIncident === "function") {
    updateTrafficChartForIncident(decision);
  }
  _renderReportTabs();
  _renderReportContent(decision);
  
  // ★ 同步更新 F4 路網圖，顯示該事件的疏散路線和事件發生點
  if (decision.routes) {
    const incidentSegmentId = decision.incident?.affected_segment || decision.incident?.affected_road || null;
    console.log(`[switchReportTab] 切換地圖到事件 ${eventId}, 事件路段: ${incidentSegmentId}`);
    updateMap(decision.routes, incidentSegmentId);
  }
}

// --- 報告放大彈窗 ---
function openReportModal() {
  if (!_currentEventId || !_allDecisions.has(_currentEventId)) return;
  const modal = document.getElementById("report-modal");
  const body = document.getElementById("report-modal-body");
  if (!modal || !body) return;

  const d = _allDecisions.get(_currentEventId);
  let html = "";

  // 結構化摘要（放大版）
  html += `<div class="report-summary">`;
  // 左欄：事件
  html += `<div>`;
  if (d.incident) {
    html += `<div class="report-section-label">EVENT</div>`;
    html += `<div style="font-size:1.1rem;font-weight:600;color:var(--text);margin-bottom:4px">${escapeHtml(d.incident.description || d.incident.type)}</div>`;
    html += `<div style="font-size:0.85rem;color:var(--text-muted)">${escapeHtml(d.incident.location || "")}</div>`;
    if (d.level) {
      const lColor = d.level === "A" ? "var(--level-a)" : "var(--level-b)";
      html += `<div style="margin-top:12px;display:inline-block;padding:4px 12px;border-radius:6px;font-size:0.8rem;font-weight:600;color:${lColor};border:2px solid ${lColor}">${d.level} 級警報</div>`;
    }
  }
  html += `</div>`;
  // 右欄：ETE + 路線
  html += `<div>`;
  if (d.ete) {
    html += `<div class="report-section-label">預計恢復時間 (ETE)</div>`;
    html += `<div style="font-size:2.2rem;font-weight:700;color:var(--text);letter-spacing:-0.03em">${d.ete.minutes} <span style="font-size:0.9rem;font-weight:400;color:var(--text-muted)">分鐘</span></div>`;
    html += `<div style="font-size:0.8rem;color:var(--text-muted);margin-top:4px;font-variant-numeric:tabular-nums">${escapeHtml(d.ete.formula || "")}</div>`;
    if (d.ete.recovery_at) html += `<div style="font-size:0.8rem;color:var(--text-muted);margin-top:2px">預計恢復：${d.ete.recovery_at}</div>`;
  }
  if (d.routes) {
    html += `<div style="margin-top:16px;font-size:0.9rem">`;
    if (d.routes.primary) html += `<div style="margin-bottom:4px"><span style="color:hsl(142,71%,45%)">●</span> <strong>主路線</strong> ${escapeHtml(d.routes.primary.name)}</div>`;
    if (d.routes.secondary) html += `<div><span style="color:hsl(48,96%,53%)">●</span> <strong>次路線</strong> ${escapeHtml(d.routes.secondary.name)}</div>`;
    html += `</div>`;
  }
  html += `</div>`;
  html += `</div>`;

  // 多語簡訊
  if (d.notifications) {
    html += `<div class="report-section">`;
    html += `<div class="report-section-label">多語通報簡訊</div>`;
    html += `<div class="report-notifications">`;
    const n = d.notifications;
    if (n.zh) html += `<div class="report-notif-item"><span class="report-notif-lang">ZH</span>${escapeHtml(n.zh)}</div>`;
    if (n.en) html += `<div class="report-notif-item"><span class="report-notif-lang">EN</span>${escapeHtml(n.en)}</div>`;
    if (n.ja) html += `<div class="report-notif-item"><span class="report-notif-lang">JA</span>${escapeHtml(n.ja)}</div>`;
    if (n.ko) html += `<div class="report-notif-item"><span class="report-notif-lang">KO</span>${escapeHtml(n.ko)}</div>`;
    html += `</div></div>`;
  }

  // 建議書全文
  if (d.control_center_report) {
    html += `<div class="report-section">`;
    html += `<div class="report-section-label">交控建議書全文</div>`;
    html += `<div class="report-full-text">${escapeHtml(d.control_center_report)}</div>`;
    html += `</div>`;
  }

  // 元資訊
  html += `<div class="report-meta">`;
  html += `<span>Trace ID: ${d.trace_id || "—"}</span>`;
  html += `<span>處理耗時: ${d.duration_ms || 0}ms</span>`;
  if (d.degraded && d.degraded.length) html += `<span style="color:var(--level-b)">降級: ${d.degraded.join(", ")}</span>`;
  html += `</div>`;

  body.innerHTML = html;
  modal.hidden = false;
}

function closeReportModal() {
  const modal = document.getElementById("report-modal");
  if (modal) modal.hidden = true;
}

// 初始化放大按鈕
function initExpandReportBtn() {
  const btn = document.getElementById("expand-report-btn");
  if (btn) {
    btn.addEventListener("click", openReportModal);
  }
}

// --- F7 決策依據分頁 ---
// Activity Log 資料結構：以 event_id 為 key 存放各事件的 log
const _activityByEvent = new Map(); // key=event_id, value={decision, logs:[]}
let _selectedActivityEventId = null;

function initF7Tabs() {
  // Activity 頁面的 tabs
  const tabsContainer = document.getElementById("activity-tabs");
  if (tabsContainer) {
    const buttons = tabsContainer.querySelectorAll("button");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        buttons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("f7-activity-feed").hidden = tab !== "activity";
        document.getElementById("f7-basis-detail").hidden = tab !== "basis";
      });
    });
  }
}

function appendActivityEntry(type, payload) {
  // 先取得 event_id（從 payload 或從目前注入的事件）
  let eventId = payload.event_id || payload.triggered_by?.[0] || _lastInjectedEventId;
  if (!eventId) return;
  
  // 確保該事件已在 Map 中
  if (!_activityByEvent.has(eventId)) {
    _activityByEvent.set(eventId, { decision: null, logs: [] });
  }
  
  const eventData = _activityByEvent.get(eventId);
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

  // 存入該事件的 logs
  eventData.logs.push({ time, label, detail, color });
  
  // 更新事件列表
  _renderActivityEventList();
  
  // 如果當前選中的是這個事件，即時更新 feed
  if (_selectedActivityEventId === eventId) {
    _renderActivityFeed(eventId);
  }
}

// 當 decision 完成時，也要記錄到對應事件
function _recordDecisionForActivity(decision) {
  if (!decision) return;
  const eventId = decision.incident?.event_id || decision.trace_id;
  if (!eventId) return;
  
  if (!_activityByEvent.has(eventId)) {
    _activityByEvent.set(eventId, { decision: null, logs: [] });
  }
  
  const eventData = _activityByEvent.get(eventId);
  eventData.decision = decision;
  
  // 更新事件列表
  _renderActivityEventList();
}

// 渲染左側事件列表
function _renderActivityEventList() {
  const list = document.getElementById("activity-event-list");
  if (!list) return;
  
  if (_activityByEvent.size === 0) {
    list.innerHTML = '<div class="activity-empty">尚無事件紀錄</div>';
    return;
  }
  
  let html = "";
  for (const [eventId, data] of _activityByEvent) {
    const isActive = eventId === _selectedActivityEventId;
    const decision = data.decision;
    const title = decision?.incident?.description || decision?.incident?.type || eventId;
    const level = decision?.level || "";
    const levelClass = level ? `level-${level.toLowerCase()}` : "";
    const logCount = data.logs.length;
    
    html += `
      <div class="activity-event-item ${levelClass} ${isActive ? 'active' : ''}" 
           onclick="selectActivityEvent('${escapeHtml(eventId)}')">
        <div class="activity-event-title">${escapeHtml(title)}</div>
        <div class="activity-event-meta">
          ${level ? `<span class="activity-event-level ${levelClass}">${level} 級</span>` : ''}
          <span class="activity-event-time">${logCount} 筆 log</span>
        </div>
      </div>
    `;
  }
  
  list.innerHTML = html;
}

// 選擇事件
function selectActivityEvent(eventId) {
  _selectedActivityEventId = eventId;
  
  // 更新列表 active 狀態
  _renderActivityEventList();
  
  // 顯示 tabs
  const tabs = document.getElementById("activity-tabs");
  if (tabs) tabs.hidden = false;
  
  // 更新 header
  const header = document.getElementById("activity-main-header");
  const eventData = _activityByEvent.get(eventId);
  if (header && eventData) {
    const title = eventData.decision?.incident?.description || eventData.decision?.incident?.type || eventId;
    header.textContent = title;
  }
  
  // 渲染 Activity Feed
  _renderActivityFeed(eventId);
  
  // 渲染 Decision Basis
  if (eventData?.decision) {
    renderDecisionBasis(eventData.decision);
  }
}

// 渲染特定事件的 Activity Feed
function _renderActivityFeed(eventId) {
  const feed = document.getElementById("f7-activity-feed");
  if (!feed) return;
  
  const eventData = _activityByEvent.get(eventId);
  if (!eventData || eventData.logs.length === 0) {
    feed.innerHTML = '<div style="color:var(--text-muted);font-size:0.75rem;padding:12px 0;">無活動紀錄</div>';
    return;
  }
  
  let html = "";
  for (const log of eventData.logs) {
    if (log.isRouteChange && log.changeRecord) {
      // 路線變更的特殊樣式
      const change = log.changeRecord;
      const oldName = _getSegmentName(change.oldPrimary) || change.oldPrimary || "N/A";
      const newName = _getSegmentName(change.newPrimary) || change.newPrimary || "N/A";
      
      html += `
        <div style="font-size:0.78rem;padding:10px;margin:6px 0;border-radius:6px;background:rgba(255,150,50,0.1);border:1px solid hsl(38,92%,50%,0.3)">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
            <span style="color:var(--text-muted);min-width:48px;font-variant-numeric:tabular-nums;font-size:0.7rem">${log.time}</span>
            <span style="color:hsl(38,92%,50%);font-weight:600">🔄 ${log.label}</span>
          </div>
          <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:4px">原因: ${escapeHtml(change.reason)}</div>
          <div style="font-size:0.72rem;display:flex;align-items:center;gap:8px">
            <span style="color:hsl(0,70%,60%)">✗ ${escapeHtml(oldName)}</span>
            <span style="color:var(--text-muted)">→</span>
            <span style="color:hsl(142,71%,45%)">✓ ${escapeHtml(newName)}</span>
          </div>
        </div>
      `;
    } else {
      // 一般 log 樣式
      html += `
        <div style="font-size:0.78rem;padding:8px 0;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px">
          <span style="color:var(--text-muted);min-width:48px;font-variant-numeric:tabular-nums;font-size:0.7rem">${log.time}</span>
          <span style="color:${log.color};font-weight:500">${log.label}</span>
          <span style="color:var(--text-muted);font-size:0.72rem">${log.detail}</span>
        </div>
      `;
    }
  }
  
  feed.innerHTML = html;
}

// 追蹤最後注入的事件 ID（供 appendActivityEntry 參考）
let _lastInjectedEventId = null;

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
    
    // 顯示原始路線（如果有變更過）
    if (decision.routes._originalPrimary) {
      html += `<div style="font-size:0.7rem;margin-bottom:8px;padding:6px 8px;background:rgba(255,100,100,0.1);border-left:3px solid hsl(0,70%,50%);border-radius:0 4px 4px 0">`;
      html += `<div style="color:hsl(0,70%,60%);font-weight:500;margin-bottom:2px">⚠ 原始路線（因飽和已更換）</div>`;
      html += `<div style="color:var(--text-muted)">● Primary: ${escapeHtml(decision.routes._originalPrimary.name)}</div>`;
      if (decision.routes._originalSecondary) {
        html += `<div style="color:var(--text-muted)">● Secondary: ${escapeHtml(decision.routes._originalSecondary.name)}</div>`;
      }
      html += `</div>`;
    }
    
    // 顯示當前路線
    if (decision.routes.primary) {
      const isChanged = decision.routes.primary._changedAt;
      const changeNote = isChanged ? ` <span style="font-size:0.6rem;color:hsl(38,92%,50%)">(已更新)</span>` : "";
      html += `<div style="font-size:0.73rem;margin-bottom:4px;color:var(--text-secondary)"><span style="color:hsl(142,71%,45%)">●</span> <strong style="color:var(--text)">Primary</strong> ${escapeHtml(decision.routes.primary.name)}${changeNote} — ${(decision.routes.primary.saturation_score * 100).toFixed(0)}% · ${decision.routes.primary.capacity_vph} vph</div>`;
    }
    if (decision.routes.secondary) {
      const isChanged = decision.routes.secondary._changedAt;
      const changeNote = isChanged ? ` <span style="font-size:0.6rem;color:hsl(38,92%,50%)">(已更新)</span>` : "";
      html += `<div style="font-size:0.73rem;margin-bottom:4px;color:var(--text-secondary)"><span style="color:hsl(48,96%,53%)">●</span> <strong style="color:var(--text)">Secondary</strong> ${escapeHtml(decision.routes.secondary.name)}${changeNote} — ${(decision.routes.secondary.saturation_score * 100).toFixed(0)}% · ${decision.routes.secondary.capacity_vph} vph</div>`;
    }
    
    // 顯示排除路段
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
  
  // 路線變更歷史
  if (decision._routeHistory && decision._routeHistory.length > 0) {
    html += `<div style="margin-bottom:12px">`;
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">ROUTE CHANGE HISTORY</div>`;
    html += `<div style="background:var(--bg-elevated);border-radius:6px;padding:8px;border:1px solid var(--border)">`;
    
    decision._routeHistory.forEach((change, idx) => {
      const time = change.time ? new Date(change.time).toLocaleTimeString("zh-TW", {hour: "2-digit", minute: "2-digit"}) : "";
      const oldName = _getSegmentName(change.oldPrimary) || change.oldPrimary;
      const newName = _getSegmentName(change.newPrimary) || change.newPrimary;
      
      html += `<div style="font-size:0.72rem;padding:6px 0;${idx > 0 ? 'border-top:1px solid var(--border);margin-top:6px;' : ''}">`;
      html += `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">`;
      html += `<span style="color:hsl(38,92%,50%);font-weight:500">🔄 第 ${idx + 1} 次重規劃</span>`;
      html += `<span style="font-size:0.65rem;color:var(--text-muted)">${time}</span>`;
      html += `</div>`;
      html += `<div style="font-size:0.68rem;color:var(--text-muted);margin-bottom:2px">原因: ${escapeHtml(change.reason)}</div>`;
      html += `<div style="font-size:0.68rem">`;
      html += `<span style="color:hsl(0,70%,60%)">✗ ${escapeHtml(oldName)}</span>`;
      html += ` → `;
      html += `<span style="color:hsl(142,71%,45%)">✓ ${escapeHtml(newName)}</span>`;
      html += `</div>`;
      html += `</div>`;
    });
    
    html += `</div></div>`;
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


// ========== Time Simulation Controls ==========

const SimState = {
  enabled: false,
  playing: false,
  startTime: null,  // Date
  endTime: null,    // Date
  currentTime: null, // Date
};

function parseISOTime(isoStr) {
  if (!isoStr) return null;
  return new Date(isoStr);
}

function formatSimTime(date) {
  if (!date) return "--:--";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function updateSimUI() {
  const statusEl = document.getElementById("sim-status");
  const statusText = statusEl?.querySelector(".sim-status-text");
  const timeDisplay = document.getElementById("sim-current-time");
  const slider = document.getElementById("sim-slider");
  const startBtn = document.getElementById("sim-start-btn");
  const playBtn = document.getElementById("sim-play-btn");
  const pauseBtn = document.getElementById("sim-pause-btn");
  const resetBtn = document.getElementById("sim-reset-btn");
  const startLabel = document.getElementById("sim-start-time");
  const endLabel = document.getElementById("sim-end-time");

  if (SimState.enabled) {
    statusEl?.classList.add("active");
    statusEl?.classList.toggle("playing", SimState.playing);
    statusText.textContent = SimState.playing ? "播放中" : "已暫停";
    
    startBtn.textContent = "停止模擬";
    startBtn.classList.add("primary");
    playBtn.disabled = SimState.playing;
    pauseBtn.disabled = !SimState.playing;
    resetBtn.disabled = false;
    slider.disabled = false;
    
    if (SimState.startTime && SimState.endTime) {
      startLabel.textContent = formatSimTime(SimState.startTime);
      endLabel.textContent = formatSimTime(SimState.endTime);
    }
  } else {
    statusEl?.classList.remove("active", "playing");
    statusText.textContent = "未啟動";
    
    startBtn.textContent = "啟動模擬";
    startBtn.classList.remove("primary");
    playBtn.disabled = true;
    pauseBtn.disabled = true;
    resetBtn.disabled = true;
    slider.disabled = true;
  }

  // 更新時間顯示和滑桿
  timeDisplay.textContent = formatSimTime(SimState.currentTime);
  
  if (SimState.startTime && SimState.endTime && SimState.currentTime) {
    const total = SimState.endTime.getTime() - SimState.startTime.getTime();
    const current = SimState.currentTime.getTime() - SimState.startTime.getTime();
    const percent = total > 0 ? (current / total) * 100 : 0;
    slider.value = Math.min(100, Math.max(0, percent));
  }
}

async function simStart() {
  if (SimState.enabled) {
    // 已啟動，停止模擬
    await fetchSimulationStop();
    SimState.enabled = false;
    SimState.playing = false;
    SimState.currentTime = null;
    // 注意：停止模擬時不清空事件框，事件仍然有效
    // 只有使用者點「重設系統」才會清空
  } else {
    // 啟動模擬
    const speed = parseInt(document.getElementById("sim-speed-select").value) || 60;
    const result = await fetchSimulationStart(speed);
    if (result.status === "ok") {
      SimState.enabled = true;
      SimState.playing = false;
      // 等 WebSocket 推播 simulation.state.v1 更新時間
    }
  }
  updateSimUI();
}

async function simPlay() {
  if (!SimState.enabled) return;
  const result = await fetchSimulationPlay();
  if (result.status === "ok") {
    SimState.playing = true;
    updateSimUI();
  }
}

async function simPause() {
  const result = await fetchSimulationPause();
  if (result.status === "ok") {
    SimState.playing = false;
    updateSimUI();
  }
}

async function simReset() {
  const result = await fetchSimulationReset();
  if (result.status === "ok") {
    SimState.playing = false;
    SimState.currentTime = SimState.startTime;
    // 注意：重置模擬時間時不清空事件框
    // 這樣可以在同一批事件上重新跑模擬，觀察不同時間點的路線變化
    // 如果要清空事件，請使用「重設系統」按鈕
    updateSimUI();
  }
}

// 滑桿拖動跳轉時間
function initSimSlider() {
  const slider = document.getElementById("sim-slider");
  if (!slider) return;
  
  slider.addEventListener("input", async () => {
    if (!SimState.enabled || !SimState.startTime || !SimState.endTime) return;
    
    const percent = parseFloat(slider.value) / 100;
    const total = SimState.endTime.getTime() - SimState.startTime.getTime();
    const targetTime = new Date(SimState.startTime.getTime() + total * percent);
    
    // 格式化為 HH:MM
    const timeStr = formatSimTime(targetTime);
    await fetchSimulationSeek(timeStr);
  });
}

// 處理 WebSocket 推播的模擬狀態
function onSimulationState(payload) {
  const action = payload.action;
  
  if (action === "started") {
    SimState.enabled = true;
    SimState.playing = false;
    SimState.startTime = parseISOTime(payload.start_time);
    SimState.endTime = parseISOTime(payload.end_time);
    SimState.currentTime = parseISOTime(payload.current_time);
  } else if (action === "playing") {
    SimState.playing = true;
  } else if (action === "paused") {
    SimState.playing = false;
  } else if (action === "reset") {
    SimState.playing = false;
    SimState.currentTime = parseISOTime(payload.current_time);
  } else if (action === "stopped") {
    SimState.enabled = false;
    SimState.playing = false;
    SimState.currentTime = null;
  } else if (action === "ended") {
    SimState.playing = false;
    SimState.currentTime = parseISOTime(payload.current_time);
  } else if (action === "seeked") {
    SimState.currentTime = parseISOTime(payload.current_time);
  }
  
  updateSimUI();
}

function onSimulationTick(payload) {
  SimState.currentTime = parseISOTime(payload.current_time);
  updateSimUI();
}

// ========== 路線重規劃處理 ==========

function onRoutesUpdated(payload) {
  console.log("[路線重規劃] 收到 routes.updated.v1:", payload);
  
  const eventId = payload.event_id;
  if (!eventId) return;
  
  // 從 _allDecisions 取得該事件的 decision
  const decision = _allDecisions.get(eventId);
  if (!decision) {
    console.warn("[路線重規劃] 找不到事件:", eventId);
    return;
  }
  
  // 記錄路線變更歷史（不覆蓋，保留歷史）
  if (!decision._routeHistory) {
    decision._routeHistory = [];
  }
  
  // 保存這次變更記錄
  const changeRecord = {
    time: payload.time || new Date().toISOString(),
    reason: payload.affected_route === "primary" ? "主路線飽和" : 
            payload.affected_route === "secondary" ? "次路線飽和" : 
            payload.affected_route === "both" ? "主次路線皆飽和" : "路線飽和",
    oldPrimary: payload.old_primary,
    newPrimary: payload.new_primary,
    oldSecondary: payload.old_secondary,
    newSecondary: payload.new_secondary,
    invalidReasons: payload.invalid_reasons || {},
    replanCount: payload.replan_count || 1,
  };
  decision._routeHistory.push(changeRecord);
  
  // 更新 routes 資訊（保留原始資料供比對）
  if (decision.routes) {
    // 標記原始路線（只在第一次變更時記錄）
    if (!decision.routes._originalPrimary && decision.routes.primary) {
      decision.routes._originalPrimary = {
        segment_id: decision.routes.primary.segment_id,
        name: decision.routes.primary.name,
      };
    }
    if (!decision.routes._originalSecondary && decision.routes.secondary) {
      decision.routes._originalSecondary = {
        segment_id: decision.routes.secondary.segment_id,
        name: decision.routes.secondary.name,
      };
    }
    
    // 更新主路線
    if (payload.new_primary && decision.routes.primary) {
      decision.routes.primary.segment_id = payload.new_primary;
      const newPrimaryName = _getSegmentName(payload.new_primary);
      if (newPrimaryName) decision.routes.primary.name = newPrimaryName;
      decision.routes.primary._changedAt = changeRecord.time;
      decision.routes.primary._changedReason = changeRecord.reason;
    }
    // 更新次路線
    if (payload.new_secondary !== undefined) {
      if (payload.new_secondary && decision.routes.secondary) {
        decision.routes.secondary.segment_id = payload.new_secondary;
        const newSecondaryName = _getSegmentName(payload.new_secondary);
        if (newSecondaryName) decision.routes.secondary.name = newSecondaryName;
        decision.routes.secondary._changedAt = changeRecord.time;
        decision.routes.secondary._changedReason = changeRecord.reason;
      } else if (!payload.new_secondary) {
        // 次路線變成 null
        decision.routes.secondary = null;
      }
    }
  }
  
  // 重新渲染報告（如果當前顯示的是這個事件）
  if (_currentEventId === eventId) {
    _renderReportContent(decision);
  }
  _renderReportTabs();
  
  // 更新 F4 路網圖
  if (decision.routes && typeof updateMap === "function") {
    updateMap(decision.routes);
  }
  
  // 更新 F7 決策依據
  if (_selectedActivityEventId === eventId) {
    renderDecisionBasis(decision);
  }
  
  // 加入 Activity Log
  _appendRouteChangeToActivity(eventId, changeRecord);
  
  // 顯示路線更新提示彈窗
  _showRouteUpdateAlert(payload);
}

// 將路線變更加入 Activity Log
function _appendRouteChangeToActivity(eventId, changeRecord) {
  if (!_activityByEvent.has(eventId)) {
    _activityByEvent.set(eventId, { decision: null, logs: [] });
  }
  
  const eventData = _activityByEvent.get(eventId);
  const time = formatTime(changeRecord.time);
  
  // 組成變更說明
  let detail = changeRecord.reason;
  if (changeRecord.oldPrimary && changeRecord.newPrimary) {
    const oldName = _getSegmentName(changeRecord.oldPrimary);
    const newName = _getSegmentName(changeRecord.newPrimary);
    detail += ` | ${oldName} → ${newName}`;
  }
  
  eventData.logs.push({
    time,
    label: "路線重規劃",
    detail,
    color: "hsl(38, 92%, 50%)",  // 橘色警告色
    isRouteChange: true,
    changeRecord,
  });
  
  // 更新事件列表
  _renderActivityEventList();
  
  // 如果當前選中的是這個事件，即時更新 feed
  if (_selectedActivityEventId === eventId) {
    _renderActivityFeed(eventId);
  }
}

// 顯示路線更新提示（需手動確認，不自動消失）
function _showRouteUpdateAlert(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const alertId = `alert-route-${++alertCounter}`;
  
  const oldPrimaryName = _getSegmentName(payload.old_primary) || payload.old_primary || "N/A";
  const newPrimaryName = _getSegmentName(payload.new_primary) || payload.new_primary || "N/A";
  const reason = payload.affected_route === "primary" ? "主路線飽和" : 
                 payload.affected_route === "secondary" ? "次路線飽和" : 
                 payload.affected_route === "both" ? "主次路線皆飽和" : "路線飽和";
  
  const alertEl = document.createElement("div");
  alertEl.className = "alert-item level-b";  // 用 B 級顏色表示警告
  alertEl.id = alertId;
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level">🔄 路線更新</span>
      <span class="alert-item-time">${payload.time ? new Date(payload.time).toLocaleTimeString("zh-TW", {hour: "2-digit", minute: "2-digit"}) : ""}</span>
    </div>
    <div class="alert-item-road">事件 ${escapeHtml(payload.event_id || "")}</div>
    <div class="alert-item-desc">${escapeHtml(reason)}，系統已重新規劃替代路線</div>
    <div class="alert-item-extra" style="margin-top:6px;padding:6px;background:rgba(0,0,0,0.2);border-radius:4px;font-size:0.72rem">
      <div style="color:hsl(0,70%,60%)">✗ 原路線: ${escapeHtml(oldPrimaryName)}</div>
      <div style="color:hsl(142,71%,45%)">✓ 新路線: ${escapeHtml(newPrimaryName)}</div>
    </div>
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')">確認</button>
  `;
  
  stack.appendChild(alertEl);
  // 路線更新提示需手動確認，不設自動關閉
}

// 輔助函式：從 segment_id 取得路段名稱
function _getSegmentName(segmentId) {
  if (!segmentId) return null;
  // 這裡可以從快取的路網資料取得名稱
  // 目前先用簡單的對照表
  const segmentNames = {
    "RD_TPE_001": "忠孝東路五段",
    "RD_TPE_002": "光復南路",
    "RD_TPE_003": "基隆路一段",
    "RD_TPE_004": "市民大道四段",
    "RD_TPE_005": "仁愛路四段",
    "RD_TPE_006": "敦化南路一段",
    "RD_TPE_007": "松高路",
    "RD_TPE_008": "延吉街",
    "RD_TPE_009": "松仁路",
    "RD_TPE_010": "永吉路",
    "RD_TPE_011": "松山路",
    "RD_TPE_012": "南京東路五段",
    "RD_TPE_013": "八德路四段",
    "RD_TPE_014": "信義路五段",
    "RD_TPE_015": "忠孝東路四段",
  };
  return segmentNames[segmentId] || segmentId;
}

// 初始化時載入模擬狀態
async function initSimulation() {
  initSimSlider();
  
  try {
    const result = await fetchSimulationState();
    if (result.status === "ok" && result.simulation) {
      const sim = result.simulation;
      SimState.enabled = sim.enabled;
      SimState.playing = sim.playing;
      SimState.startTime = parseISOTime(sim.start_time);
      SimState.endTime = parseISOTime(sim.end_time);
      SimState.currentTime = parseISOTime(sim.current_time);
      updateSimUI();
    }
  } catch (e) {
    console.warn("載入模擬狀態失敗:", e);
  }
}
