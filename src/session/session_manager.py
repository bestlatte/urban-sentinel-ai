"""W2：handle_message / record_response / clear_session。純 Python，零 LLM。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W2-session-manager/design.md`
（已修正版：session_id 不靠 WebSocket connection 推導；record_response 直接收
user_message 參數，沒有 _pending_message 暫存機制）。
"""

from __future__ import annotations

from src.session.models import Session, W1Context

MAX_HISTORY = 10

SESSION_STORE: dict[str, Session] = {}
"""行程內記憶體物件，Server 重啟即遺失（Demo 可接受，見 design.md 第六節錯誤處理）。"""


def handle_message(session_id: str, user_message: str) -> W1Context:
    """收到使用者新訊息時呼叫（由 orchestrator.handle_user_query() 呼叫，不是前端直接呼叫）。

    TODO(Kiro): 依 design.md 第四節「handle_message 流程」實作：
    取得或建立 session → 組合最近 MAX_HISTORY 輪上下文 → 回傳 W1Context。
    """
    raise NotImplementedError("見 W2-session-manager/design.md 第4.1節")


def record_response(
    session_id: str,
    user_message: str,
    ai_response: str,
    triggered_sops: list[int] | None = None,
    new_assumptions: dict[str, float | int | str] | None = None,
) -> None:
    """W1 回覆完成後呼叫，把這輪對話存入 history、更新 assumptions。

    user_message 由呼叫端直接傳入（呼叫端本來就同時握有這個值），不靠暫存屬性。
    session_id 不存在時靜默忽略，不報錯（session 已被清除的正常情況）。
    """
    raise NotImplementedError("見 W2-session-manager/design.md 第4.2節")


def clear_session(session_id: str) -> None:
    """使用者點擊清除按鈕時呼叫（走 WebSocket chat.clear_session.v1，例外不走REST）。"""
    raise NotImplementedError("見 W2-session-manager/design.md 第4.3節")
