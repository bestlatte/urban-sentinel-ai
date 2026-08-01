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
    context_snapshot: dict | None = None
    """回答當下的世界長什麼樣（評估時刻、主/次線、飽和度、重規劃次數、ETE…）。

    [2026-08-02] 這是「情況變了要主動說」的資料基礎。事實區塊每輪都會重新讀
    最新的 `decision_result`，所以**事實本身**一直是新的；但對話歷史裡塞的是
    當時的回答原文，模型會同時看到

        顧問（上一輪）：主線市民大道四段，飽和度 0.78
        事實區塊（現在）：主線 仁愛路四段，飽和度 0.85

    而沒有任何一句話告訴它哪個是現在、中間發生了什麼。存下這份快照，
    下一輪才 diff 得出來（見 `whatif_agent.build_change_block()`）。

    刻意存 dict 而不是物件：session 是純記憶體的，存 dict 不會讓
    `IncidentRecord` 被一直參照著、也不會因為決策物件被替換而跟著變動——
    快照必須凍結在當時，否則 diff 永遠是空的。
    """


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
    """**這一輪實際生效**的假設，不一定等於 session 裡存的那份。

    新的假設情境會把舊的取代掉（見 `session_manager.resolve_assumption_scope()`），
    被丟掉的那些在 `dropped_assumptions` 裡，要讓使用者看見。
    """
    dropped_assumptions: dict[str, float | int | str] = field(default_factory=dict)
    """本輪因為「這是新的假設情境」而被清掉的舊假設。

    丟掉不能是靜默的：使用者先問「如果基隆路塌」再問「如果光復南路塌」，
    系統決定不把基隆路帶進來是對的，但他必須知道系統做了這個決定。
    """
    assumption_scope: str = "carry"
    """本輪對舊假設的處置：`carry`（沿用）/ `replace`（取代）/ `merge`（明確疊加）。

    供留痕與前端提示用；判斷邏輯見 `session_manager.resolve_assumption_scope()`。
    """
    last_snapshot: dict | None = None
    """上一輪回答當下的世界快照，用來 diff 出「自上次以來的變化」。"""
