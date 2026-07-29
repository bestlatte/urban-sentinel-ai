/**
 * WebSocket 連線管理 + message_type 分派。
 * 參考 spec：04-system-architecture.md §5 總表、F6-chat-ui/design.md 第五節。
 * 斷線後 3 秒自動重連；前端不透過 WS 送問題（走 REST），WS 只收推播。
 */

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    ChatState.wsConnection = ws;
    console.log("[WS] connected");
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
