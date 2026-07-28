/**
 * WebSocket 連線、指數退避重連、斷線時輪詢 GET /api/dashboard、依 message_type 分派。
 * 不直接改 DOM（那是 app.js/chat-render.js 的工作）。
 *
 * 參考 spec：m5-api-orchestrator-dashboard/design.md 第五節、
 * .kiro/steering/04-system-architecture.md §5 完整 message_type 總表。
 * 全部訊息都是完整 Message Envelope，依 envelope.message_type 分派給對應 handler，
 * F1-F7 共用同一條連線，各模組的前端 js 只處理自己認得的 message_type、忽略其他。
 */

// TODO(Kiro): connectWebSocket(), 依 message_type 前綴分派給 app.js（dashboard.*／decision.*／
// rules.*）或 chat-app.js（chat.*／whatif.*／trace.*）。
