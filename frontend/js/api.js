/**
 * Fetch 四個 REST 端點、Envelope 拆封、錯誤碼轉可讀訊息。不解讀業務欄位。
 * 參考 spec：m5-api-orchestrator-dashboard/design.md 第六節。
 */

// TODO(Kiro): fetchDashboard(), evaluateIncident(eventId), postWhatIf(body) —
// postWhatIf 的回應可能是 whatif.evaluated.v1/WhatIfResult 或
// trace.answered.v1/TraceAnswer，依 message_type 分派（見
// .kiro/steering/04-system-architecture.md §5）。
