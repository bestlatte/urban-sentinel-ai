"""處理過程中透過 WebSocket 逐步推送 loading 進度。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第十一節。
推播訊息要套 Message Envelope，message_type 用 `chat.loading_step.v1`
（不是裸字串 "loading_step"，見 `F6-chat-ui/design.md` 已修正版）。
"""

LOADING_STEPS = [
    "解析問題意圖",
    "檢索 SOP 條款",
    "呼叫決策模組",
    "計算 ETE",
    "組合回覆",
]

# TODO(Kiro): Strands Agent 目前不支援 streaming tool call 事件；design.md 建議
# 方案A（tool function 內部主動推播）或方案B（退化為兩段式：開始→完成）。
# 先實作方案B保證能用，有時間再改方案A。
