"""W2 內部資料結構：Turn / Session / W1Context。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W2-session-manager/design.md`（已修正版——
`_pending_message` 暫存機制已移除，`record_response()` 改直接收 user_message 參數，
不要照抄該資料夾內舊版任務拆解裡殘留的暫存屬性寫法）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src import clock


@dataclass
class Turn:
    """一輪對話 = 使用者問一次 + AI 答一次。"""

    user_message: str
    ai_response: str
    timestamp: datetime
    triggered_sops: list[int] = field(default_factory=list)


@dataclass
class Session:
    """一個對話 session 的完整狀態，純記憶體物件。"""

    session_id: str
    """由前端（F6）頁面載入時產生一次，隨每次 POST /api/what-if 請求帶上——
    不依賴 WebSocket connection 推導（design.md 第五節修正版）。"""
    history: list[Turn] = field(default_factory=list)
    assumptions: dict[str, float | int | str] = field(default_factory=dict)
    """key 格式 "{entity}.{field}"，同一 key 被重新假設時覆蓋舊值。"""
    created_at: datetime = field(default_factory=clock.now)


@dataclass
class W1Context:
    """W2 組合好、交給 W1 的完整上下文。"""

    session_id: str
    new_message: str
    history: list[Turn]
    """最近 N 輪，N <= MAX_HISTORY（10）。"""
    accumulated_assumptions: dict[str, float | int | str]
