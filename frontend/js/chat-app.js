/**
 * 主入口：初始化、WebSocket 訊息分派、sendMessage()（呼叫 POST /api/what-if）。
 *
 * 參考 spec：m3-bedrock-advisor/F6-chat-ui/design.md 第三、五節（2026-07-28
 * 二次修正版——**送出訊息走 REST，不是 WebSocket**：sendMessage() 呼叫
 * `POST /api/what-if`，同步等回應直接 renderAIResponse()；handleServerMessage()
 * 只處理 loading 進度推播與 chat.response.v1 冗餘推播（用 correlation_id 去重，
 * 見 design.md 該處程式碼），不要照抄該文件更早期「送WebSocket chat_message」的舊寫法。
 * buildEnvelope() 輔助函式也已在 design.md 給出，只用於 clear_session 這個
 * 唯一維持走 WebSocket 的例外。
 */
