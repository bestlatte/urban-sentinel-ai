/**
 * 單一狀態物件、渲染排程、KPI／決策依據／建議書卡片、載入動畫。
 * 不判定 traffic_level、不算 ETE——只做「payload欄位 → DOM文字/class」的映射。
 *
 * 參考 spec：m5-api-orchestrator-dashboard/design.md 第六節；
 * 版面渲染規則：traffic_level 值直接對應 CSS class，不在 JS 比較任何門檻。
 *
 * [2026-07-28總架構師補充：業界通用版原型] KPI 卡片、F7活動feed、F7決策依據
 * 分頁的具體渲染函式簽章如下，內容留給 Kiro／團隊實作。
 */

const AppState = {
  dashboard: null, // 最近一次 DashboardPayload
  decision: null, // 最近一次 DecisionResult
  activityLog: [], // decision.cycle_start.v1 / decision.task_update.v1 累積的時間軸項目
};

// --- F1 KPI（五張卡片，見 src/models.py KpiSummary） ---
function renderKpis(kpis) {
  // TODO(Kiro): 五個 data-kpi 卡片依序填入 active_incident_count / current_level /
  // average_saturation / multilingual_alert_count / system_mode；
  // current_level 用 CSS class .level-a/.level-b/.level-normal，不在此比較門檻。
}

// --- F7 分頁切換（即時活動 / 決策依據） ---
function initF7Tabs() {
  // TODO(Kiro): 點擊 .f7-tabs button 切換 [data-tab-panel] 的 hidden 屬性。
}

function appendActivityEntry(entry) {
  // TODO(Kiro): entry 來自 decision.cycle_start.v1（{trace_id, triggered_by}）
  // 或 decision.task_update.v1（{trace_id, dispatch_seq, status}），
  // 累加進 #f7-activity-feed 的時間軸，同一 trace_id 的項目分組顯示。
}

function renderDecisionBasis(decisionResult) {
  // TODO(Kiro): 顯示 decisionResult.routes.candidates 每個候選的 eligible/reason_code，
  // decisionResult 對應的 RuleHit.clause_id + SOP條款內容（需另外查 SopClause）。
  // 「查看推理過程」按鈕呼叫 generate_report_explanation(trace_id) 的結果顯示於此。
}

// --- F5 建議書／簡訊卡片 ---
function renderReportCard(decisionResult) {
  // TODO(Kiro): 顯示 control_center_report 全文；notifications 依語言分頁或並排顯示。
}

// --- F2 異常自動彈窗 ---
function showAlertModal(alertPayload) {
  // TODO(Kiro): 收到 decision.alert.v1 時顯示 #f2-alert-modal，
  // {level, description, ete_minutes} 映射進彈窗文字。
}

// --- WS 訊息分派入口（由 ws.js 呼叫） ---
function handleAppMessage(envelope) {
  switch (envelope.message_type) {
    case "dashboard.updated.v1":
      AppState.dashboard = envelope.payload;
      renderKpis(envelope.payload.kpis);
      break;
    case "decision.alert.v1":
      showAlertModal(envelope.payload);
      break;
    case "decision.cycle_start.v1":
    case "decision.task_update.v1":
      appendActivityEntry(envelope.payload);
      break;
    case "decision.completed.v1":
      AppState.decision = envelope.payload;
      renderDecisionBasis(envelope.payload);
      renderReportCard(envelope.payload);
      break;
  }
}
