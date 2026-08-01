/**
 * WebSocket 連線管理 + message_type 分派。
 * 參考 spec：04-system-architecture.md §5 總表、F6-chat-ui/design.md 第五節。
 * 斷線後 3 秒自動重連；前端不透過 WS 送問題（走 REST），WS 只收推播。
 *
 * [2026-07-28架構複查新增：回應2026-07-28_架構圖合規性複查與待辦.md §2.6]
 * `architecture-json-live.mmd` 把 FWS 節點標成「接收推播・斷線退回輪詢」，原本這裡
 * 只有「斷線後重連 WebSocket」，沒有斷線期間的 REST 輪詢退路——如果 WS 一直連不上
 * （網路問題、伺服器重啟中），畫面會完全停在斷線那一刻，沒有任何更新，直到重連成功。
 * 現在補上：斷線時啟動輪詢 `fetchDashboard()`，重連成功後停止輪詢。
 */

const _POLLING_FALLBACK_INTERVAL_MS = 8000;
let _pollingFallbackTimer = null;

function _startPollingFallback() {
  if (_pollingFallbackTimer !== null) return; // 已經在跑，不要重複啟動
  console.log("[WS] 啟動輪詢退路（每 8 秒抓一次 /api/dashboard）");
  _pollingFallbackTimer = setInterval(async () => {
    try {
      const data = await fetchDashboard();
      if (data.status === "ok" && data.payload && typeof renderDashboard === "function") {
        renderDashboard(data.payload);
      }
    } catch (e) {
      console.warn("[WS] 輪詢退路失敗", e);
    }
  }, _POLLING_FALLBACK_INTERVAL_MS);
}

function _stopPollingFallback() {
  if (_pollingFallbackTimer === null) return;
  clearInterval(_pollingFallbackTimer);
  _pollingFallbackTimer = null;
  console.log("[WS] WebSocket 已重連，停止輪詢退路");
}

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    ChatState.wsConnection = ws;
    console.log("[WS] connected");
    _stopPollingFallback();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleServerMessage(msg);
    } catch (e) {
      console.warn("[WS] 無法解析訊息", e);
    }
  };

  ws.onclose = () => {
    ChatState.wsConnection = null;
    console.log("[WS] disconnected, 3s 後重連");
    _startPollingFallback();
    setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.warn("[WS] error", err);
  };
}

function handleServerMessage(msg) {
  const type = msg.message_type;
  const payload = msg.payload;

  switch (type) {
    case "dashboard.updated.v1":
      if (typeof onDashboardUpdated === "function") onDashboardUpdated(payload);
      break;

    case "decision.alert.v1":
      if (typeof showAlertModal === "function") showAlertModal(payload);
      break;

    case "decision.cycle_start.v1":
      if (typeof appendActivityEntry === "function") appendActivityEntry("cycle_start", payload);
      break;

    case "decision.task_update.v1":
      if (typeof appendActivityEntry === "function") appendActivityEntry("task_update", payload);
      // 帶 eta_seconds 的階段（建議書生成、決策說明）另外畫全域進度條，
      // 否則那 15~20 秒畫面上只有活動面板多一行字，太容易被當成當機。
      if (typeof onTaskUpdateProgress === "function") onTaskUpdateProgress(payload);
      break;

    case "decision.completed.v1":
      if (typeof onDecisionCompleted === "function") onDecisionCompleted(payload);
      break;

    case "rules.evaluated.v1":
      if (typeof onRulesEvaluated === "function") onRulesEvaluated(payload);
      break;

    case "whatif.evaluated.v1":
      // 冗餘推播（REST 已同步回傳），用 correlation_id 去重
      if (payload.correlation_id === ChatState.currentCorrelationId) return;
      renderAIResponse(payload);
      break;

    case "chat.loading_start.v1":
      // [2026-08-02] 本地 `sendMessage()` 已經畫過一次思考中泡泡，這裡再畫就是
      // 第二個（守衛是「correlation_id 不符才 return」，也就是**相符時才畫**，
      // 而本地那次用的正是同一個 id）。`renderLoadingStart()` 現在是冪等的，
      // 所以這一行退化成保險：只有在本地沒畫成功時才會真的生出泡泡。
      if (payload.correlation_id !== ChatState.currentCorrelationId) return;
      renderLoadingStart(payload.steps || []);
      break;

    case "chat.loading_step.v1":
      if (payload.correlation_id !== ChatState.currentCorrelationId) return;
      if (payload.all_done) removeLoading();
      break;

    case "chat.response.v1":
      // 冗餘推播，用 correlation_id 去重
      if (payload.correlation_id === ChatState.currentCorrelationId) return;
      removeLoading();
      renderAIResponse(payload);
      break;

    case "chat.input_lock.v1":
      ChatState.isLocked = !!payload.locked;
      break;

    case "chat.system_status.v1":
      if (typeof updateStatusBanner === "function") updateStatusBanner(payload);
      break;

    case "chat.session_cleared.v1":
      // 確認清除完成
      break;

    // ===== Simulation 相關推播 =====
    case "simulation.state.v1":
      if (typeof onSimulationState === "function") onSimulationState(payload);
      break;

    case "simulation.tick.v1":
      if (typeof onSimulationTick === "function") onSimulationTick(payload);
      break;

    // ===== 路線重規劃推播 =====
    case "routes.updated.v1":
      if (typeof onRoutesUpdated === "function") onRoutesUpdated(payload);
      break;

    // 建議書背景補寫完成。路線在 routes.updated.v1 時就已經更新了，
    // 這一則只換文字——兩者分開推是為了不讓 LLM 的 20 秒擋住路線更新。
    case "report.updated.v1":
      if (typeof onReportUpdated === "function") onReportUpdated(payload);
      break;

    // ===== 事件解除推播 =====
    case "incident.resolved.v1":
      if (typeof onIncidentResolved === "function") onIncidentResolved(payload);
      break;

    default:
      console.log("[WS] 未處理的 message_type:", type);
  }
}

function sendWsClearSession() {
  if (!ChatState.wsConnection) return;
  ChatState.wsConnection.send(JSON.stringify({
    message_type: "chat.clear_session.v1",
    payload: { session_id: ChatState.sessionId },
  }));
}
