"""W2：handle_message / record_response / clear_session。純 Python，零 LLM。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W2-session-manager/design.md`
（已修正版：session_id 不靠 WebSocket connection 推導；record_response 直接收
user_message 參數，沒有 _pending_message 暫存機制）。
"""

from __future__ import annotations

from src import clock

from src.session.models import Session, Turn, W1Context

MAX_HISTORY = 10

SESSION_STORE: dict[str, Session] = {}
"""行程內記憶體物件，Server 重啟即遺失（Demo 可接受，見 design.md 第六節錯誤處理）。"""


_HYPOTHETICAL_MARKERS = ("如果", "假設", "假如", "若是", "若", "要是", "萬一")
"""「這是一個**新的**假設情境」的判斷詞。

與 `orchestrator._FORWARD_LOOKING_WORDS` 有重疊但用途不同：那組是「要不要走
前瞻分支」，這組是「要不要沿用既有假設」。刻意不共用——哪天前瞻分支的詞要調整，
不該連帶改變假設的生命週期。
"""

_CONTINUATION_MARKERS = (
    "同時", "再加上", "加上", "而且", "並且", "另外還", "除此之外",
    "在此基礎", "延續", "接著再", "一起",
)
"""明確表示「要疊加在既有假設之上」的措辭。

只認**明說**的疊加。像「也」「還」這種詞太常出現在一般語句裡
（「那 ETE 也要重算嗎」根本不是疊加），拿來當判斷會誤傷。
"""


def _contains(text: str, markers) -> bool:
    return any(m in text for m in markers)


def resolve_assumption_scope(user_message: str) -> str:
    """這一輪要怎麼處理既有假設：`carry` / `replace` / `merge`。

    [2026-08-02 新增：修「chatbot 分不出新問題」的核心]
    ------------------------------------------------
    先講清楚問題出在哪：真正污染上下文的不是對話歷史，是 `session.assumptions`。
    它是 `{entity}.{field}` 的 dict，同 key 覆蓋、**不同 key 永久累加、永不過期**，
    而 prompt 明文要求「必須把累積假設一併帶入 simulate_scenario」。

    於是先問「如果基隆路一段坍塌」、再問「光復南路現在怎樣」，第二題仍帶著
    基隆路的假設去重算。實測回覆裡那句「這是進行中的事件（與您剛才假設的基隆路
    坍塌無關）」不是模型貼心，是它在跟被污染的上下文搏鬥。

    判斷必須發生在**組 prompt 之前**——污染是在送進 LLM 那一刻造成的，
    等回來再修存檔已經來不及。所以只能用確定性的措辭判斷，不能再叫一次 LLM
    （多一輪往返、而且分類本身也會錯）。

    三條規則：

        含假設詞 + 含延續詞  → merge   「如果光復南路**同時**也塌呢」
        含假設詞             → replace 「如果光復南路塌呢」＝另一個獨立情境
        不含假設詞           → carry   「為什麼」「那 ETE 呢」＝追問現有情境

    第三條最容易被忽略但最重要：對**現有情境**的追問必須留著假設，
    否則使用者問「那 ETE 呢」會突然變成在問沒有假設的世界。

    判錯的成本由 UI 兜住：生效中的假設會以 chips 顯示、可個別移除，
    被丟掉的假設也會明白告訴使用者。系統不需要猜對 100%，只需要**讓人看得見**。
    """
    text = user_message or ""
    if not _contains(text, _HYPOTHETICAL_MARKERS):
        return "carry"
    if _contains(text, _CONTINUATION_MARKERS):
        return "merge"
    return "replace"


def handle_message(session_id: str, user_message: str) -> W1Context:
    """收到使用者新訊息時呼叫（由 orchestrator.handle_user_query() 呼叫，不是前端直接呼叫）。

    取得或建立 session → 決定假設作用域 → 組合最近 MAX_HISTORY 輪上下文
    → 回傳 W1Context。
    """
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = Session(session_id=session_id)

    session = SESSION_STORE[session_id]
    recent_history = session.history[-MAX_HISTORY:]

    scope = resolve_assumption_scope(user_message)
    if scope == "replace":
        effective: dict[str, float | int | str] = {}
        dropped = session.assumptions.copy()
    else:
        effective = session.assumptions.copy()
        dropped = {}

    # 上一輪回答當下的世界快照，供 `build_change_block()` diff
    last_snapshot = recent_history[-1].context_snapshot if recent_history else None

    return W1Context(
        session_id=session_id,
        new_message=user_message,
        history=recent_history,
        accumulated_assumptions=effective,
        dropped_assumptions=dropped,
        assumption_scope=scope,
        last_snapshot=last_snapshot,
    )


def record_response(
    session_id: str,
    user_message: str,
    ai_response: str,
    triggered_sops: list[int] | None = None,
    new_assumptions: dict[str, float | int | str] | None = None,
    assumption_scope: str = "carry",
    context_snapshot: dict | None = None,
) -> None:
    """W1 回覆完成後呼叫，把這輪對話存入 history、更新 assumptions。

    user_message 由呼叫端直接傳入（呼叫端本來就同時握有這個值），不靠暫存屬性。
    session_id 不存在時靜默忽略，不報錯（session 已被清除的正常情況）。

    [2026-08-02] `assumption_scope` 決定這輪算完之後 session 裡要留下什麼：
    `replace` 表示使用者提的是一個新的獨立情境，舊假設在 `handle_message()`
    就已經沒有進 prompt，這裡也要真的從 session 抹掉——否則下一輪
    「那 ETE 呢」（carry）又會把它們撈回來，等於白清一場。
    """
    session = SESSION_STORE.get(session_id)
    if session is None:
        return

    turn = Turn(
        user_message=user_message,
        ai_response=ai_response,
        timestamp=clock.now(),
        triggered_sops=triggered_sops or [],
        context_snapshot=context_snapshot,
    )
    session.history.append(turn)

    if assumption_scope == "replace":
        session.assumptions = dict(new_assumptions or {})
    elif new_assumptions:
        session.assumptions.update(new_assumptions)

    # 超過上限就裁切
    if len(session.history) > MAX_HISTORY:
        session.history = session.history[-MAX_HISTORY:]


def drop_assumption(session_id: str, key: str) -> dict[str, float | int | str]:
    """移除單一假設條件（前端的假設 chip 按 × 時呼叫），回傳剩下的。

    比「整段對話重來」精細：使用者常常只是想拿掉其中一個假設繼續問，
    不需要連前面問過的東西一起丟。
    """
    session = SESSION_STORE.get(session_id)
    if session is None:
        return {}
    session.assumptions.pop(key, None)
    return session.assumptions.copy()


def get_assumptions(session_id: str) -> dict[str, float | int | str]:
    """目前生效中的假設條件（供前端顯示 chips）。"""
    session = SESSION_STORE.get(session_id)
    return session.assumptions.copy() if session else {}


def clear_session(session_id: str) -> None:
    """使用者點擊清除按鈕時呼叫（走 WebSocket chat.clear_session.v1，例外不走REST）。"""
    SESSION_STORE.pop(session_id, None)
