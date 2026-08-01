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
  initGeoMap();
  initF7Tabs();
  initF3InjectForm();
  initHeaderClock();
  initExpandReportBtn();
  initRightSideNav();
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

function setRightSideNavCollapsed(collapsed) {
  const sidebar = document.querySelector(".right-side-nav");
  const toggle = document.querySelector(".right-side-nav-toggle");
  if (!sidebar || !toggle) return;

  sidebar.classList.toggle("collapsed", collapsed);
  document.body.classList.toggle("right-side-nav-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", collapsed ? "展開側邊欄" : "收縮側邊欄");
  toggle.title = collapsed ? "展開側邊欄" : "收縮側邊欄";
}

function initRightSideNav() {
  let collapsed = false;
  try {
    collapsed = localStorage.getItem("citynexus-right-side-nav-collapsed") === "true";
  } catch (error) {
    console.warn("無法讀取右側欄偏好:", error);
  }
  setRightSideNavCollapsed(collapsed);
}

function toggleRightSideNav() {
  const sidebar = document.querySelector(".right-side-nav");
  if (!sidebar) return;
  const collapsed = !sidebar.classList.contains("collapsed");
  setRightSideNavCollapsed(collapsed);
  try {
    localStorage.setItem("citynexus-right-side-nav-collapsed", String(collapsed));
  } catch (error) {
    console.warn("無法儲存右側欄偏好:", error);
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
  
  // 切換到 Reports 頁面時，渲染報告列表
  if (pageName === "reports") {
    renderReportsEventList();
  }
}

// --- F1 KPI ---
const _injectedEventNames = new Map();
let _activeIncidentCount = 0;
let _levelACounts = 0;
let _levelBCounts = 0;
let _severityCritical = 0;
let _severityHigh = 0;
let _severityMedium = 0;

function _formatInjectedEventName(incident) {
  if (!incident) return "未知事件";
  const typeName = _getShortType(incident.type || "未知事件");
  return incident.location ? `${typeName}（${incident.location}）` : typeName;
}

function _renderInjectedEventsKpi() {
  const card = document.querySelector('.kpi-card[data-kpi="latest_injected_event"]');
  if (!card) return;
  const names = [..._injectedEventNames.values()];
  const content = names.length
    ? names.map((name) => `<div class="kpi-event-name" title="${escapeHtml(name)}">${escapeHtml(name)}</div>`).join("")
    : '<div class="kpi-event-empty">尚未注入</div>';
  card.innerHTML = `<div class="kpi-value kpi-event-list">${content}</div><div class="kpi-label">事件注入名稱</div>`;
}

function _recordInjectedEvent(decision) {
  const incident = decision?.incident;
  const eventId = incident?.event_id || decision?.trace_id;
  if (!eventId) return;
  _injectedEventNames.set(eventId, _formatInjectedEventName(incident));
  _renderInjectedEventsKpi();
}

function renderKpis(kpis) {
  if (!kpis) return;
  const values = [
    { key: "active_incident_count", label: "進行中事件", value: _activeIncidentCount },
  ];

  values.forEach(({ key, label, value }) => {
    const card = document.querySelector(`.kpi-card[data-kpi="${key}"]`);
    if (card) card.innerHTML = `<div class="kpi-value" title="${escapeHtml(String(value))}">${escapeHtml(String(value))}</div><div class="kpi-label">${label}</div>`;
  });
  _renderInjectedEventsKpi();
  _renderLevelKpi();
}

function _renderLevelKpi() {
  const card = document.querySelector('.kpi-card[data-kpi="current_level"]');
  if (!card) return;
  card.innerHTML = `<div class="kpi-value" style="font-size:0.85rem;line-height:1.6">
    <span style="color:var(--level-a);font-weight:700">${_severityCritical} Critical</span><br>
    <span style="color:var(--level-b);font-weight:700">${_severityHigh} High</span><br>
    <span style="color:hsl(45,93%,40%);font-weight:700">${_severityMedium} Medium</span>
  </div><div class="kpi-label">事件嚴重度分佈</div>`;
}
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
  
  const eventId = decision.incident?.event_id || decision.trace_id;
  
  // ★ 判斷是否為 cascade replan 後的更新
  // 如果 _allDecisions 已有此事件，且 routes 有變化，則視為 replan 更新
  const existingDecision = eventId ? _allDecisions.get(eventId) : null;
  const isReplanUpdate = existingDecision && _isRoutesChanged(existingDecision.routes, decision.routes);
  
  if (isReplanUpdate) {
    console.log(`[onDecisionCompleted] 收到 cascade replan 更新: ${eventId}`);
    // replan 更新：跳過去重檢查，直接更新
    _handleReplanDecisionUpdate(decision, eventId);
    return;
  }
  
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
    // 同步更新地理圖
    if (typeof updateGeoMap === "function") updateGeoMap(decision.routes);
  }
  // 標記事故在地理圖上
  if (decision.incident && typeof markIncidentOnGeoMap === "function") {
    markIncidentOnGeoMap(decision.incident);
  }
  
  // 飽和地圖更新由 decision.alert.v1 負責，不在這裡處理
  
  // 更新 F5 報告（結構化摘要 + 全文）
  renderReportCard(decision);
  // 更新 F7 決策依據
  renderDecisionBasis(decision);
  // 更新 KPI（事件數）
  const countCard = document.querySelector('.kpi-card[data-kpi="active_incident_count"]');
  if (countCard) {
    _activeIncidentCount += 1;
    countCard.innerHTML = `<div class="kpi-value">${_activeIncidentCount}</div><div class="kpi-label">進行中事件</div>`;
  }
  // 更新等級 KPI（依事件嚴重度）
  const severity = decision.incident?.severity;
  if (severity === "Critical") _severityCritical++;
  else if (severity === "High") _severityHigh++;
  else if (severity === "Medium") _severityMedium++;
  _renderLevelKpi();
  
  // 更新 Reports 頁面列表（如果在該頁面）
  _updateReportsOnNewDecision();
}

// ★ 判斷兩個 routes 是否有變化（用於識別 cascade replan 更新）
function _isRoutesChanged(oldRoutes, newRoutes) {
  if (!oldRoutes && !newRoutes) return false;
  if (!oldRoutes || !newRoutes) return true;
  
  const oldPrimary = oldRoutes.primary?.segment_id;
  const newPrimary = newRoutes.primary?.segment_id;
  const oldSecondary = oldRoutes.secondary?.segment_id;
  const newSecondary = newRoutes.secondary?.segment_id;
  
  return oldPrimary !== newPrimary || oldSecondary !== newSecondary;
}

// ★ 處理 cascade replan 後的 decision 更新（不增加事件計數，只更新顯示）
function _handleReplanDecisionUpdate(decision, eventId) {
  console.log(`[_handleReplanDecisionUpdate] 更新事件 ${eventId} 的路線`);
  
  // 更新 _allDecisions 中的 decision
  if (eventId && _allDecisions.has(eventId)) {
    const oldDecision = _allDecisions.get(eventId);
    // 保留 _routeHistory 等自訂欄位
    if (oldDecision._routeHistory) {
      decision._routeHistory = oldDecision._routeHistory;
    }
    _allDecisions.set(eventId, decision);
  }
  
  // 更新 F4 路網圖
  if (decision.routes) {
    const incidentSegmentId = decision.incident?.affected_segment || decision.incident?.affected_road || null;
    console.log(`[_handleReplanDecisionUpdate] 更新地圖，事件路段: ${incidentSegmentId}`);
    updateMap(decision.routes, incidentSegmentId);
  }
  
  // 更新 F5 報告（如果當前顯示的是這個事件）
  if (_currentEventId === eventId) {
    _renderReportContent(decision);
  }
  _renderReportTabs();
  
  // 更新 F7 決策依據
  if (_selectedActivityEventId === eventId) {
    renderDecisionBasis(decision);
  }
  
  // 記錄到 Activity Log
  _appendReplanUpdateToActivity(eventId, decision);
}

// ★ 將 cascade replan 記錄到 Activity Log
function _appendReplanUpdateToActivity(eventId, decision) {
  if (!_activityByEvent.has(eventId)) return;
  
  const eventData = _activityByEvent.get(eventId);
  const time = formatTime(new Date().toISOString());
  
  const primaryName = decision.routes?.primary?.name || decision.routes?.primary?.segment_id || "(無)";
  
  eventData.logs.push({
    time,
    label: "路線優化（事件解除觸發）",
    detail: `新主路線: ${primaryName}`,
    color: "hsl(142, 71%, 45%)",  // 綠色（正面變化）
    isRouteChange: true,
  });
  
  // 更新事件列表
  _renderActivityEventList();
  
  // 如果當前選中的是這個事件，即時更新 feed
  if (_selectedActivityEventId === eventId) {
    _renderActivityFeed(eventId);
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
  
  // ★ 從 incident 取得 timestamp 並格式化為 HH:MM
  const timestamp = decision.incident?.timestamp;
  console.log("[addIncidentToLevelBox] timestamp:", timestamp);
  let timeStr = "";
  if (timestamp) {
    try {
      const d = new Date(timestamp);
      if (!isNaN(d.getTime())) {
        timeStr = d.toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false });
      } else {
        // 嘗試從字串直接解析 "2026-05-20 22:10" 格式
        const match = timestamp.match(/(\d{2}):(\d{2})/);
        if (match) timeStr = `${match[1]}:${match[2]}`;
      }
    } catch (e) {
      // fallback: 直接取字串中的時間部分
      const match = String(timestamp).match(/(\d{2}):(\d{2})/);
      if (match) timeStr = `${match[1]}:${match[2]}`;
    }
  }
  console.log("[addIncidentToLevelBox] timeStr:", timeStr);
  
  // ★ 添加 onclick 事件，點擊時切換地圖和報告
  const itemHtml = `
    <div class="incident-item" data-event-id="${escapeHtml(eventId)}" onclick="selectIncidentFromList('${escapeHtml(eventId)}')" style="cursor:pointer;">
      <div class="incident-item-title">
        ${timeStr ? `<span class="incident-time">[${timeStr}]</span> ` : ""}${escapeHtml(title)}
      </div>
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
  // 等級 KPI 改由 _renderLevelKpi 統一管理，rules.evaluated 不覆蓋
  // 更新 KPI：多語通報站點（從 rule_hits 計算 SOP-6 命中數）
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
  
  // 判斷是「事件注入」還是「模擬器路段預警」
  const isIncidentAlert = (payload.ete_minutes != null) || payload.severity || !payload.road_name;
  
  let levelLabel, levelClass;
  
  if (isIncidentAlert && payload.severity) {
    // 事件注入：顯示事件嚴重度 (Critical/High/Medium)
    switch (payload.severity) {
      case "Critical":
        levelLabel = "Critical 級警報";
        levelClass = "level-critical";
        break;
      case "High":
        levelLabel = "High 級警報";
        levelClass = "level-high";
        break;
      case "Medium":
        levelLabel = "Medium 級警報";
        levelClass = "level-medium";
        break;
      default:
        levelLabel = `${payload.severity} 級警報`;
        levelClass = "level-b";
    }
  } else {
    // 路段飽和預警：顯示交通等級 (A/B)
    const isA = payload.level === "A";
    levelLabel = isA ? "A 級警報" : "B 級警報";
    levelClass = isA ? "level-a" : "level-b";
  }
  
  const alertId = `alert-${++alertCounter}`;
  
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
    
    // ★ 從 timestamp 取得時間 (格式: "2026-05-20 22:10" 或 ISO)
    let timeStr = "";
    if (e.timestamp) {
      const match = String(e.timestamp).match(/(\d{2}):(\d{2})/);
      if (match) timeStr = `[${match[1]}:${match[2]}] `;
    }
    
    return `<button type="button" onclick="injectIncident('${escapeHtml(e.event_id)}')" ${disabledAttr} title="${escapeHtml(e.event_id)}\n${escapeHtml(e.description || '')}">${timeStr}${shortType}（${shortLocation}）${checkMark}</button>`;
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
  _injectedEventNames.clear();
  _renderInjectedEventsKpi();
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
      _recordInjectedEvent(decision);
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
      _injectedEventNames.clear();
      _activeIncidentCount = 0;
      _levelACounts = 0;
      _levelBCounts = 0;
      _severityCritical = 0;
      _severityHigh = 0;
      _severityMedium = 0;
      _renderInjectedEventsKpi();
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
    
    // ★ 模擬器模式：使用模擬器當前時間做飽和度查詢
    // enabled=true 表示模擬器已啟動（即使暫停中也要用模擬時間）
    let asOfTime = null;
    if (SimState.enabled && SimState.currentTime) {
      asOfTime = SimState.currentTime.toISOString();
      console.log(`[injectIncident] 模擬器模式，使用時間: ${SimState.currentTime.toLocaleTimeString('zh-TW')}`);
    }
    
    const data = await fetchEvaluateIncident(eventId, asOfTime);
    console.log(`[injectIncident] API 回應:`, data);
    
    if (data.status === "ok" && data.payload) {
      const decision = data.payload;
      console.log(`[injectIncident] decision.routes:`, decision.routes);
      _recordInjectedEvent(decision);
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

  // 除錯：確認收到的 decision 內容
  console.log("[_renderReportContent] decision:", decision);
  console.log("[_renderReportContent] notifications:", decision.notifications);
  console.log("[_renderReportContent] control_center_report:", decision.control_center_report);
  console.log("[_renderReportContent] merged_incident_info:", decision.merged_incident_info);

  // 啟用放大按鈕
  const expandBtn = document.getElementById("expand-report-btn");
  if (expandBtn) expandBtn.disabled = false;

  let html = "";

  // ★ 同路段多事件合併資訊（放在最前面）
  if (decision.merged_incident_info && decision.merged_incident_info.count > 1) {
    html += _renderMergedIncidentInfo(decision);
  }

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

  // 建議書全文
  if (decision.control_center_report) {
    html += `<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:6px">FULL REPORT</div>`;
    html += `<div style="font-size:0.75rem;line-height:1.7;color:var(--text-secondary);white-space:pre-wrap">${escapeHtml(decision.control_center_report)}</div>`;
  }

  // 元資訊
  html += `<div style="margin-top:14px;padding-top:10px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">`;
  html += `<div style="font-size:0.62rem;color:var(--text-muted);display:flex;gap:16px;font-variant-numeric:tabular-nums">`;
  html += `<span>${decision.trace_id || "—"}</span>`;
  html += `<span>${decision.duration_ms || 0}ms</span>`;
  if (decision.degraded && decision.degraded.length) html += `<span style="color:var(--level-b)">${decision.degraded.join(", ")}</span>`;
  html += `</div>`;
  
  // ★ 解除事件按鈕（只有未解除的事件才顯示）
  const eventId = decision.incident?.event_id || decision.trace_id;
  if (!decision._resolved) {
    html += `<button onclick="resolveIncident('${escapeHtml(eventId)}')" 
      style="padding:4px 12px;border-radius:4px;font-size:0.68rem;border:1px solid hsl(142,71%,45%);
             background:transparent;color:hsl(142,71%,45%);cursor:pointer;transition:all 0.15s;"
      onmouseover="this.style.background='hsl(142,71%,45%)';this.style.color='#000'"
      onmouseout="this.style.background='transparent';this.style.color='hsl(142,71%,45%)'"
      title="標記此事件已解除，釋放封閉路段">✓ 解除事件</button>`;
  } else {
    html += `<span style="font-size:0.68rem;color:hsl(142,71%,45%)">✓ 已解除</span>`;
  }
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

// --- Map Tab Switch ---
function switchMapTab(tab) {
  const schematic = document.getElementById("f4-map");
  const geo = document.getElementById("f4-geomap");
  const buttons = document.querySelectorAll(".map-tab");
  if (!schematic || !geo) return;

  if (tab === "geographic") {
    schematic.style.display = "none";
    geo.style.display = "block";
    buttons.forEach(b => b.classList.toggle("active", b.textContent.trim() === "Geographic"));
  } else {
    schematic.style.display = "block";
    geo.style.display = "none";
    buttons.forEach(b => b.classList.toggle("active", b.textContent.trim() === "Schematic"));
  }
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
    // ★ 模擬器啟動時，依起始時間載入事件列表
    _lastIncidentUpdateTime = null;  // 重設，強制更新
    updateIncidentListByTime(SimState.currentTime);
  } else if (action === "playing") {
    SimState.playing = true;
  } else if (action === "paused") {
    SimState.playing = false;
  } else if (action === "reset") {
    SimState.playing = false;
    SimState.currentTime = parseISOTime(payload.current_time);
    // ★ 重設時重新載入事件列表
    _lastIncidentUpdateTime = null;
    updateIncidentListByTime(SimState.currentTime);
  } else if (action === "stopped") {
    SimState.enabled = false;
    SimState.playing = false;
    SimState.currentTime = null;
    // ★ 停止模擬時，顯示全部事件
    _lastIncidentUpdateTime = null;
    initF3InjectForm();  // 載入全部事件
  } else if (action === "ended") {
    SimState.playing = false;
    SimState.currentTime = parseISOTime(payload.current_time);
  } else if (action === "seeked") {
    SimState.currentTime = parseISOTime(payload.current_time);
    // ★ 跳轉時間時更新事件列表
    _lastIncidentUpdateTime = null;
    updateIncidentListByTime(SimState.currentTime);
  }
  
  updateSimUI();
}

function onSimulationTick(payload) {
  SimState.currentTime = parseISOTime(payload.current_time);
  updateSimUI();
  
  // ★ 模擬器播放時，依當前時間更新事件注入面板
  if (SimState.enabled && SimState.currentTime) {
    updateIncidentListByTime(SimState.currentTime);
  }
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
  
  // ★ 更新報告書與簡訊內容（使用後端重新生成的版本）
  if (payload.control_center_report !== undefined) {
    decision.control_center_report = payload.control_center_report;
    console.log("[路線重規劃] 報告書已更新");
  }
  if (payload.notifications !== undefined) {
    decision.notifications = payload.notifications;
    console.log("[路線重規劃] 簡訊內容已更新");
  }
  
  // 重新渲染報告（如果當前顯示的是這個事件）
  if (_currentEventId === eventId) {
    _renderReportContent(decision);
  }
  _renderReportTabs();
  
  // ★ 更新 F4 路網圖（傳入事件路段 ID）
  if (decision.routes && typeof updateMap === "function") {
    const incidentSegmentId = decision.incident?.affected_segment || decision.incident?.affected_road || null;
    console.log(`[路線重規劃] 更新地圖，事件路段: ${incidentSegmentId}`);
    updateMap(decision.routes, incidentSegmentId);
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

// ========== 事件解除處理 ==========

// ★ 呼叫後端 API 解除事件
async function resolveIncident(eventId) {
  if (!eventId) return;
  
  // 確認對話框
  const confirmed = confirm(`確定要解除事件 ${eventId}？\n\n這會釋放封閉的路段，讓其他事件可以重新評估替代路線。`);
  if (!confirmed) return;
  
  try {
    console.log(`[resolveIncident] 開始解除事件: ${eventId}`);
    
    const res = await fetch(`/api/incidents/${encodeURIComponent(eventId)}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "Resolved" }),
    });
    
    const data = await res.json();
    console.log("[resolveIncident] API 回應:", data);
    
    if (data.status === "ok") {
      // 成功：WebSocket 會推播 incident.resolved.v1，由 onIncidentResolved 處理 UI 更新
      // 這裡先立即更新本地狀態，避免 UI 延遲
      const decision = _allDecisions.get(eventId);
      if (decision) {
        decision._resolved = true;
        decision._resolvedAt = data.resolved_at;
        decision._freedSegment = data.freed_segment;
        // 重新渲染報告卡片（會顯示「已解除」而非按鈕）
        if (_currentEventId === eventId) {
          _renderReportContent(decision);
        }
      }
      
      console.log(`[resolveIncident] 事件 ${eventId} 已解除，受影響事件: ${data.affected_incidents?.join(", ") || "無"}`);
    } else {
      alert(`解除失敗: ${data.errors?.[0]?.message || "未知錯誤"}`);
    }
  } catch (e) {
    console.error("[resolveIncident] 解除失敗:", e);
    alert("解除事件失敗，請稍後再試");
  }
}

function onIncidentResolved(payload) {
  console.log("[事件解除] 收到 incident.resolved.v1:", payload);
  
  const eventId = payload.event_id;
  if (!eventId) return;
  
  // 從活躍事件列表移除（移到歷史）
  const decision = _allDecisions.get(eventId);
  if (decision) {
    decision._resolved = true;
    decision._resolvedAt = payload.resolved_at;
    decision._freedSegment = payload.freed_segment;
  }
  
  // 更新 UI：將事件標記為已解除
  _markIncidentAsResolved(eventId, payload);
  
  // 顯示解除通知
  _showIncidentResolvedAlert(payload);
  
  // 更新 KPI
  _updateKpiAfterResolve();
}

function _markIncidentAsResolved(eventId, payload) {
  // 在事件等級框中標記為已解除
  const levels = ["a", "b"];
  for (const level of levels) {
    const list = document.getElementById(`incident-list-${level}`);
    if (!list) continue;
    const item = list.querySelector(`[data-event-id="${eventId}"]`);
    if (item) {
      item.style.opacity = "0.5";
      item.style.textDecoration = "line-through";
      item.insertAdjacentHTML("beforeend", `<div style="font-size:0.6rem;color:hsl(142,71%,45%);margin-top:4px">✓ 已解除</div>`);
    }
  }
  
  // 在報告 tabs 中標記
  const tabsContainer = document.getElementById("f5-report-tabs");
  if (tabsContainer) {
    const btn = tabsContainer.querySelector(`button[onclick="switchReportTab('${eventId}')"]`);
    if (btn) {
      btn.style.opacity = "0.6";
      btn.textContent = btn.textContent + " (已解除)";
    }
  }
}

function _showIncidentResolvedAlert(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const alertId = `alert-resolved-${++alertCounter}`;
  const freedSegmentName = _getSegmentName(payload.freed_segment) || payload.freed_segment || "未知路段";
  
  const alertEl = document.createElement("div");
  alertEl.className = "alert-item level-resolved";
  alertEl.id = alertId;
  alertEl.style.cssText = "border-left-color: hsl(142,71%,45%); background: linear-gradient(135deg, hsla(142,71%,25%,0.3), hsla(142,71%,35%,0.1));";
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level" style="color:hsl(142,71%,45%)">✓ 事件解除</span>
      <span class="alert-item-time">${payload.resolved_at ? new Date(payload.resolved_at).toLocaleTimeString("zh-TW", {hour: "2-digit", minute: "2-digit"}) : ""}</span>
    </div>
    <div class="alert-item-road">${escapeHtml(payload.event_id)}</div>
    <div class="alert-item-desc">路段 ${escapeHtml(freedSegmentName)} 已解封，可重新納入路線規劃</div>
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')">確認</button>
  `;
  
  stack.appendChild(alertEl);
}

function _updateKpiAfterResolve() {
  const countCard = document.querySelector('.kpi-card[data-kpi="active_incident_count"]');
  if (countCard) {
    _activeIncidentCount = Math.max(0, _activeIncidentCount - 1);
    countCard.innerHTML = `<div class="kpi-value">${_activeIncidentCount}</div><div class="kpi-label">進行中事件</div>`;
  }
}

// ========== 特殊警報類型處理 ==========

// 更新 showAlertModal 以處理新的 alert_type
const _originalShowAlertModal = showAlertModal;
showAlertModal = function(payload) {
  // 檢查是否為特殊類型警報
  if (payload.alert_type) {
    switch (payload.alert_type) {
      case "NO_FEASIBLE_ROUTE":
        _showNoFeasibleRouteAlert(payload);
        return;
      case "ROUTE_CHANGED":
        _showRouteChangedAlert(payload);
        return;
      case "ROUTE_OPTIMIZED":
        _showRouteOptimizedAlert(payload);
        return;
      case "INCIDENT_UPDATED":
        _showIncidentUpdatedAlert(payload);
        return;
    }
  }
  
  // 一般警報走原本的邏輯
  _originalShowAlertModal(payload);
};

function _showNoFeasibleRouteAlert(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const alertId = `alert-nofeasible-${++alertCounter}`;
  
  const alertEl = document.createElement("div");
  alertEl.className = "alert-item level-medium";
  alertEl.id = alertId;
  alertEl.style.cssText = "border-left-color: hsl(45,93%,47%); background: #F9F0D4;";
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level" style="color:hsl(45,80%,30%);font-weight:700">⚠️ 嚴重警告</span>
    </div>
    <div class="alert-item-road" style="color:#34271D;font-size:0.9rem;font-weight:700">無可用替代路線</div>
    <div class="alert-item-desc" style="color:#4a3728;font-weight:500">${escapeHtml(payload.description)}</div>
    <div class="alert-item-extra" style="color:#665244;font-weight:600">請立即啟動人工指揮或封閉區域</div>
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')" style="background:#34271D;color:#F9F0D4;font-weight:600">確認</button>
  `;
  
  stack.appendChild(alertEl);
}

function _showRouteChangedAlert(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const alertId = `alert-routechange-${++alertCounter}`;
  const oldName = _getSegmentName(payload.old_primary) || payload.old_primary || "N/A";
  const newName = _getSegmentName(payload.new_primary) || payload.new_primary || "N/A";
  
  const alertEl = document.createElement("div");
  alertEl.className = "alert-item level-b";
  alertEl.id = alertId;
  alertEl.style.cssText = "border-left-color: hsl(38,92%,50%);";
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level" style="color:hsl(38,92%,50%)">🔄 路線變更</span>
    </div>
    <div class="alert-item-road">連鎖衝突自動重規劃</div>
    <div class="alert-item-desc">${escapeHtml(payload.description)}</div>
    <div class="alert-item-extra" style="margin-top:6px;padding:6px;background:rgba(0,0,0,0.2);border-radius:4px;font-size:0.72rem">
      <div style="color:hsl(0,70%,60%)">✗ 原路線: ${escapeHtml(oldName)}</div>
      <div style="color:hsl(142,71%,45%)">✓ 新路線: ${escapeHtml(newName)}</div>
    </div>
    ${payload.ete_minutes ? `<div class="alert-item-extra">新 ETE: ${payload.ete_minutes} 分鐘</div>` : ""}
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')">確認</button>
  `;
  
  stack.appendChild(alertEl);
}

function _showRouteOptimizedAlert(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const alertId = `alert-routeopt-${++alertCounter}`;
  const oldName = _getSegmentName(payload.old_primary) || payload.old_primary || "N/A";
  const newName = _getSegmentName(payload.new_primary) || payload.new_primary || "N/A";
  
  const alertEl = document.createElement("div");
  alertEl.className = "alert-item level-info";
  alertEl.id = alertId;
  alertEl.style.cssText = "border-left-color: hsl(200,70%,50%);";
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level" style="color:hsl(200,70%,60%)">🚀 路線優化</span>
    </div>
    <div class="alert-item-road">發現更佳路線</div>
    <div class="alert-item-desc">${escapeHtml(payload.description)}</div>
    <div class="alert-item-extra" style="margin-top:6px;padding:6px;background:rgba(0,0,0,0.2);border-radius:4px;font-size:0.72rem">
      <div style="color:var(--text-muted)">● 原路線: ${escapeHtml(oldName)}</div>
      <div style="color:hsl(142,71%,45%)">✓ 優化路線: ${escapeHtml(newName)}</div>
    </div>
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')">確認</button>
  `;
  
  stack.appendChild(alertEl);
}

function _showIncidentUpdatedAlert(payload) {
  const stack = document.getElementById("alert-stack");
  if (!stack) return;
  
  const alertId = `alert-updated-${++alertCounter}`;
  
  const alertEl = document.createElement("div");
  alertEl.className = "alert-item level-b";
  alertEl.id = alertId;
  alertEl.innerHTML = `
    <div class="alert-item-header">
      <span class="alert-item-level">📝 事件更新</span>
    </div>
    <div class="alert-item-road">${escapeHtml(payload.description)}</div>
    ${payload.ete_minutes ? `<div class="alert-item-extra">重算 ETE: ${payload.ete_minutes} 分鐘</div>` : ""}
    <button class="alert-item-close" onclick="dismissAlertItem('${alertId}')">確認</button>
  `;
  
  stack.appendChild(alertEl);
}

// ========== 同路段多事件合併顯示 ==========

// 渲染報告內容時處理合併事件資訊
function _renderMergedIncidentInfo(decision) {
  if (!decision.merged_incident_info || decision.merged_incident_info.count <= 1) {
    return "";
  }
  
  const info = decision.merged_incident_info;
  let html = `
    <div style="margin-bottom:16px;padding:12px;background:linear-gradient(135deg, hsla(270,50%,30%,0.3), hsla(270,50%,40%,0.1));border:1px solid hsl(270,50%,50%,0.4);border-radius:8px">
      <div style="font-size:0.72rem;color:hsl(270,70%,70%);font-weight:600;margin-bottom:8px">
        📋 同路段多事件合併 (${info.count} 件)
      </div>
      <div style="font-size:0.7rem;color:var(--text-muted);margin-bottom:6px">
        合併事件: ${info.event_ids.map(id => `<code style="background:var(--bg-elevated);padding:1px 4px;border-radius:3px;margin:0 2px">${escapeHtml(id)}</code>`).join("")}
      </div>
  `;
  
  if (info.descriptions && info.descriptions.length > 0) {
    html += `<div style="font-size:0.68rem;color:var(--text-secondary);margin-top:8px;padding-top:8px;border-top:1px solid hsl(270,50%,50%,0.2)">`;
    info.descriptions.forEach((desc, i) => {
      html += `<div style="margin:3px 0">${i + 1}. ${escapeHtml(desc)}</div>`;
    });
    html += `</div>`;
  }
  
  html += `
      <div style="margin-top:10px;padding:8px;background:rgba(0,0,0,0.2);border-radius:4px">
        <div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:4px">ETE 合併計算</div>
        <div style="font-size:0.75rem;color:var(--text)">
          max(各事件ETE) = <strong>${info.max_ete_minutes}</strong> 分鐘
        </div>
        <div style="font-size:0.75rem;color:var(--text)">
          + 協調延遲 (${info.count - 1} × 15) = <strong>${(info.count - 1) * 15}</strong> 分鐘
        </div>
        <div style="font-size:0.85rem;color:hsl(48,96%,60%);font-weight:600;margin-top:4px">
          合併 ETE = <strong>${info.merged_ete_minutes}</strong> 分鐘
        </div>
      </div>
    </div>
  `;
  
  return html;
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

// ★ 依模擬時間更新事件注入面板
let _lastIncidentUpdateTime = null;

async function updateIncidentListByTime(currentTime) {
  if (!currentTime) return;
  
  // 每分鐘才更新一次（避免太頻繁呼叫 API）
  const currentMinute = currentTime.getMinutes();
  if (_lastIncidentUpdateTime === currentMinute) return;
  _lastIncidentUpdateTime = currentMinute;
  
  const form = document.getElementById("incident-inject-form");
  if (!form) return;
  
  try {
    // 呼叫 API 取得該時間點可用的事件
    const asOf = currentTime.toISOString();
    const data = await fetchIncidents(asOf);
    
    if (data.status === "ok" && data.incidents) {
      // 比較事件數量是否有變化
      const newCount = data.incidents.length;
      const oldCount = _availableIncidents.length;
      
      _availableIncidents = data.incidents;
      renderIncidentButtons(form);
      
      // 如果有新事件出現，用 console 記錄（可選：加視覺提示）
      if (newCount > oldCount) {
        console.log(`[模擬器] ${formatSimTime(currentTime)} 有 ${newCount - oldCount} 筆新事件可注入`);
      }
    }
  } catch (e) {
    console.warn("更新事件列表失敗:", e);
  }
}


// ========== Reports 頁面邏輯 ==========

let _selectedReportEventId = null;

// 渲染 Reports 頁面的事件列表
function renderReportsEventList() {
  const list = document.getElementById("reports-event-list");
  if (!list) return;
  
  if (_allDecisions.size === 0) {
    list.innerHTML = '<div class="reports-empty">尚無事件報告</div>';
    return;
  }
  
  let html = "";
  for (const [eventId, decision] of _allDecisions) {
    const isActive = eventId === _selectedReportEventId;
    const title = decision.incident?.description || decision.incident?.type || eventId;
    const level = decision.level || "";
    const levelClass = level ? `level-${level.toLowerCase()}` : "";
    const location = decision.incident?.location || "";
    const eteMinutes = decision.ete?.minutes;
    
    html += `
      <div class="reports-event-item ${levelClass} ${isActive ? 'active' : ''}" 
           onclick="selectReportEvent('${escapeHtml(eventId)}')">
        <div class="reports-event-item-title">${escapeHtml(title)}</div>
        <div class="reports-event-item-meta">
          ${level ? `<span class="reports-event-item-level ${levelClass}">${level} 級</span>` : ''}
          ${location ? `<span class="reports-event-item-location">${escapeHtml(location)}</span>` : ''}
        </div>
        ${eteMinutes ? `<div class="reports-event-item-ete">ETE: <strong>${eteMinutes}</strong> 分鐘</div>` : ''}
      </div>
    `;
  }
  
  list.innerHTML = html;
}

// 選擇事件並顯示報告詳情
function selectReportEvent(eventId) {
  _selectedReportEventId = eventId;
  
  // 更新列表 active 狀態
  renderReportsEventList();
  
  // 取得 decision 資料
  const decision = _allDecisions.get(eventId);
  if (!decision) return;
  
  // 更新標題
  const header = document.getElementById("reports-main-header");
  if (header) {
    const title = decision.incident?.description || decision.incident?.type || eventId;
    const level = decision.level || "";
    const levelClass = level ? `level-${level.toLowerCase()}` : "";
    header.innerHTML = `
      <span>${escapeHtml(title)}</span>
      ${level ? `<span class="reports-main-header-level ${levelClass}">${level} 級</span>` : ''}
    `;
  }
  
  // 渲染報告內容
  renderReportDetail(decision);
}

// 渲染報告詳情
function renderReportDetail(decision) {
  const container = document.getElementById("reports-detail-content");
  if (!container) return;
  
  let html = "";
  
  // === 摘要區 ===
  html += `<div class="report-summary-grid">`;
  
  // 事件資訊
  html += `<div class="report-summary-item">`;
  html += `<div class="report-summary-label">事件資訊</div>`;
  if (decision.incident) {
    html += `<div class="report-summary-value">${escapeHtml(decision.incident.description || decision.incident.type)}</div>`;
    html += `<div class="report-summary-sub">${escapeHtml(decision.incident.location || "")}</div>`;
    if (decision.incident.severity) {
      html += `<div class="report-summary-sub">嚴重度：${escapeHtml(decision.incident.severity)}</div>`;
    }
  }
  html += `</div>`;
  
  // ETE
  html += `<div class="report-summary-item">`;
  html += `<div class="report-summary-label">預計恢復時間 (ETE)</div>`;
  if (decision.ete) {
    html += `<div class="report-summary-value large">${decision.ete.minutes} <span style="font-size:0.5em;font-weight:400;color:var(--text-muted)">分鐘</span></div>`;
    if (decision.ete.formula) {
      html += `<div class="report-summary-sub" style="font-variant-numeric:tabular-nums">${escapeHtml(decision.ete.formula)}</div>`;
    }
    if (decision.ete.recovery_at) {
      html += `<div class="report-summary-sub">預計恢復時間：${escapeHtml(decision.ete.recovery_at)}</div>`;
    }
  } else {
    html += `<div class="report-summary-value">—</div>`;
  }
  html += `</div>`;
  
  html += `</div>`; // end summary-grid
  
  // === 路線規劃 ===
  if (decision.routes && (decision.routes.primary || decision.routes.secondary)) {
    html += `<div class="report-section">`;
    html += `<div class="report-section-title">疏散路線規劃</div>`;
    html += `<div class="report-routes">`;
    
    if (decision.routes.primary) {
      const p = decision.routes.primary;
      const changedNote = p._changedAt ? ' (已更新)' : '';
      html += `
        <div class="report-route-item">
          <div class="report-route-dot primary"></div>
          <div class="report-route-info">
            <div class="report-route-name">主路線：${escapeHtml(p.name)}${changedNote}</div>
            <div class="report-route-meta">飽和度 ${(p.saturation_score * 100).toFixed(0)}% · 容量 ${p.capacity_vph} vph</div>
          </div>
        </div>
      `;
    }
    
    if (decision.routes.secondary) {
      const s = decision.routes.secondary;
      const changedNote = s._changedAt ? ' (已更新)' : '';
      html += `
        <div class="report-route-item">
          <div class="report-route-dot secondary"></div>
          <div class="report-route-info">
            <div class="report-route-name">次路線：${escapeHtml(s.name)}${changedNote}</div>
            <div class="report-route-meta">飽和度 ${(s.saturation_score * 100).toFixed(0)}% · 容量 ${s.capacity_vph} vph</div>
          </div>
        </div>
      `;
    }
    
    html += `</div></div>`;
    
    // 排除路段
    if (decision.routes.excluded && decision.routes.excluded.length > 0) {
      html += `<div class="report-section">`;
      html += `<div class="report-section-title">排除路段</div>`;
      html += `<div style="display:flex;flex-direction:column;gap:6px;">`;
      decision.routes.excluded.forEach(e => {
        html += `<div style="font-size:0.8rem;color:var(--text-muted);padding:8px 12px;background:var(--bg-elevated);border-radius:var(--radius-sm);border:1px solid var(--border);">`;
        html += `<span style="color:hsl(0,70%,60%);">✗</span> ${escapeHtml(e.name)} — <code style="font-size:0.7rem;background:var(--bg);padding:2px 6px;border-radius:3px;">${escapeHtml(e.reason_code)}</code>`;
        html += `</div>`;
      });
      html += `</div></div>`;
    }
  }
  
  // === 交控建議書全文 ===
  if (decision.control_center_report) {
    html += `<div class="report-section">`;
    html += `<div class="report-section-title">交控建議書全文</div>`;
    html += `<div class="report-full-content">${escapeHtml(decision.control_center_report)}</div>`;
    html += `</div>`;
  }
  
  // === 簡訊通報 ===
  if (decision.notifications) {
    const notifs = decision.notifications;
    const hasNotifs = notifs.zh || notifs.en || notifs.ja || notifs.ko;
    
    if (hasNotifs) {
      html += `<div class="report-section">`;
      html += `<div class="report-section-title">多語簡訊通報</div>`;
      html += `<div class="report-notifications">`;
      
      if (notifs.zh) {
        html += `<div class="report-notif-item">
          <div class="report-notif-lang">中文 (ZH)</div>
          <div class="report-notif-text">${escapeHtml(notifs.zh)}</div>
        </div>`;
      }
      if (notifs.en) {
        html += `<div class="report-notif-item">
          <div class="report-notif-lang">English (EN)</div>
          <div class="report-notif-text">${escapeHtml(notifs.en)}</div>
        </div>`;
      }
      if (notifs.ja) {
        html += `<div class="report-notif-item">
          <div class="report-notif-lang">日本語 (JA)</div>
          <div class="report-notif-text">${escapeHtml(notifs.ja)}</div>
        </div>`;
      }
      if (notifs.ko) {
        html += `<div class="report-notif-item">
          <div class="report-notif-lang">한국어 (KO)</div>
          <div class="report-notif-text">${escapeHtml(notifs.ko)}</div>
        </div>`;
      }
      
      html += `</div></div>`;
    }
  }
  
  // === 觸發的 SOP ===
  if (decision.triggered_by && decision.triggered_by.length > 0) {
    html += `<div class="report-section">`;
    html += `<div class="report-section-title">觸發的 SOP</div>`;
    html += `<div style="display:flex;flex-wrap:wrap;gap:8px;">`;
    decision.triggered_by.forEach(sop => {
      html += `<span style="display:inline-block;padding:6px 12px;border-radius:6px;font-size:0.78rem;background:var(--bg-elevated);border:1px solid var(--border);color:var(--text-secondary);">${escapeHtml(sop)}</span>`;
    });
    html += `</div></div>`;
  }
  
  // === 元資訊 ===
  html += `<div class="report-meta-info">`;
  html += `<span>Trace ID: ${escapeHtml(decision.trace_id || "—")}</span>`;
  html += `<span>處理耗時: ${decision.duration_ms || 0}ms</span>`;
  if (decision.routes?.duration_ms !== undefined) {
    const slaOk = decision.routes.within_60_second_sla;
    html += `<span style="color:${slaOk ? 'var(--success)' : 'var(--level-a)'}">路網規劃: ${decision.routes.duration_ms}ms ${slaOk ? '✓' : '✗ SLA exceeded'}</span>`;
  }
  if (decision.degraded && decision.degraded.length > 0) {
    html += `<span class="report-degraded">降級: ${decision.degraded.join(", ")}</span>`;
  }
  if (decision.is_simulated) {
    html += `<span style="color:hsl(270,50%,60%);">模擬模式</span>`;
  }
  html += `</div>`;
  
  container.innerHTML = html;
}

// 當新決策完成時，同步更新 Reports 列表
function _updateReportsOnNewDecision() {
  // 如果目前在 Reports 頁面，即時更新列表
  const reportsPage = document.getElementById("page-reports");
  if (reportsPage && !reportsPage.hidden) {
    renderReportsEventList();
  }
}
