"""Bedrock 實際可用性的單一真相來源。

為什麼需要這個檔案
------------------
[2026-08-01] 在此之前，全系統判斷「Bedrock 能不能用」的方式只有一種：讀
`USE_BEDROCK` 這個環境變數。問題是那個旗標說的是「**允不允許**呼叫」，
不是「呼叫**通不通**」。兩者一旦分歧（憑證失效、金鑰被停用、斷網、模型下架），
系統會顯示成功但實際上全程降級：

    GET /api/health          → {"use_bedrock": true}      ← 讀旗標，騙人
    Dashboard KPI 系統模式    → "Live"                     ← 讀旗標，騙人
    交控建議書                → 安靜退成模板版              ← 唯一的徵兆

也就是說，Demo 現場如果 Bedrock 不通，畫面上一切正常，只有文字風格變樸素，
**要很熟悉這套系統的人才看得出來**。這違反本專案反覆引用的「永不沉默」原則。

本模組把「Bedrock 現在到底通不通」變成一個有明確答案的問題：

  - `probe()`      啟動時真的送一次請求驗證（不是猜）
  - `record_success()` / `record_failure()`  每次真實呼叫的結果都回報進來
  - `get_status()` 供 `/api/health`、Dashboard KPI、WebSocket 狀態橫幅共用

刻意不做的事
------------
不做自動重試、不做定期輪詢。狀態由**真實流量**驅動——每次 LLM 呼叫的成敗本來
就是最準確的探針，另外再開一個背景輪詢只是多花錢重複同一件事。啟動探測是唯一
的例外，因為那時候還沒有任何真實流量。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_TZ_TAIPEI = timezone(timedelta(hours=8))

PROBE_TIMEOUT_S = 10.0
"""啟動探測的逾時。比一般呼叫短——探測用的 prompt 只有幾個 token，正常應該
1~2 秒回來。等太久沒有意義，Demo 前的人在盯著終端機。"""

_CREDENTIAL_ERROR_MARKERS = (
    "ExpiredToken",
    "InvalidClientTokenId",
    "UnrecognizedClientException",
    "AccessDeniedException",
    "InvalidSignatureException",
    "SignatureDoesNotMatch",
    "NoCredentialsError",
    "CredentialRetrievalError",
)
"""憑證類錯誤的特徵字串。

這類錯誤跟「模型忙碌」「逾時」不同——**不會自己好**，必須有人去換憑證。
分開判斷是為了讓橫幅講得出可行動的話（「憑證失效，請更新」vs「連線不穩」），
而不是一律顯示「LLM 不可用」讓人不知道該做什麼。
"""

_MODEL_ERROR_MARKERS = (
    "ResourceNotFoundException",
    "end of its life",
    "ValidationException",
)
"""模型類錯誤：模型 ID 打錯、模型下架、未開通。同樣不會自己好。"""


class _State:
    """狀態容器。用鎖保護是因為寫入端來自多個執行緒——決策週期、W1 對話、
    啟動探測全都跑在不同的 `asyncio.to_thread` 工作執行緒上。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reachable: bool | None = None
        """None = 還沒驗證過（剛啟動、或 USE_BEDROCK=false 根本沒驗）。

        刻意區分 None 與 False：「不知道」跟「確定不通」對使用者是兩件事，
        前者該顯示「檢查中」，後者該顯示紅字。
        """
        self.last_ok_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_kind: str | None = None  # credential | model | network | None
        self.last_model_id: str | None = None
        """最後一次**成功**呼叫實際用的模型 ID。

        這是「我到底在用哪個模型」唯一可信的答案——設定檔寫什麼不代表真的用了
        那個，環境變數可能被覆寫、可能有 fallback。這裡記的是實際送出去的值。
        """
        self.last_latency_ms: int | None = None
        self.success_count: int = 0
        self.failure_count: int = 0
        self.consecutive_failures: int = 0
        """連續失敗次數（成功時歸零）。用於區分「一次網路抖動」與「真的掛了」。"""


_STATE = _State()

_broadcaster = None
"""狀態變化時的推播函式（`ws_manager.broadcast`）。由 `main.py` 啟動時設定。"""


def set_broadcaster(fn) -> None:
    """登記 WebSocket 廣播函式。未登記時狀態變化只寫日誌，不推播。"""
    global _broadcaster
    _broadcaster = fn


def _classify_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if any(m in text for m in _CREDENTIAL_ERROR_MARKERS):
        return "credential"
    if any(m in text for m in _MODEL_ERROR_MARKERS):
        return "model"
    return "network"


NETWORK_FAILURE_TOLERANCE = 2
"""網路類失敗要連續幾次才判定為「不可用」。

[2026-08-01 實測後加入] 只失敗一次就翻紅會太吵：實測跑一輪決策週期時，M4B
解釋鏈遇到一次 `Connection was closed before we received a valid response`，
下一次呼叫立刻就成功了。那種瞬斷會讓 Demo 現場的狀態橫幅閃一下紅字再自己
恢復——比不顯示更讓人分心，因為它看起來像系統不穩，其實只是一個封包。

只寬容網路類錯誤。憑證與模型類錯誤**第一次就翻**，因為那兩種不會自己好：
等第二次只是延後通知，而使用者早一秒知道就早一秒能去換憑證。
"""


def record_success(model_id: str | None = None, latency_ms: int | None = None) -> None:
    """一次成功的 Bedrock 呼叫。狀態由不通轉為通時會推播。"""
    with _STATE.lock:
        changed = _STATE.reachable is not True
        _STATE.reachable = True
        _STATE.last_ok_at = datetime.now(tz=_TZ_TAIPEI)
        _STATE.last_error = None
        _STATE.last_error_kind = None
        _STATE.success_count += 1
        _STATE.consecutive_failures = 0
        if model_id:
            _STATE.last_model_id = model_id
        if latency_ms is not None:
            _STATE.last_latency_ms = latency_ms

    if changed:
        logger.info("Bedrock 恢復可用（model=%s）", model_id)
        _broadcast_status()


def record_failure(exc: BaseException) -> None:
    """一次失敗的 Bedrock 呼叫。

    **不是每次失敗都代表 Bedrock 掛了**——單次瞬斷很常見（實測有過）。所以網路類
    錯誤要連續 `NETWORK_FAILURE_TOLERANCE` 次才翻成不可用；憑證與模型類錯誤
    第一次就翻，因為那兩種不會自己好。

    無論翻不翻，`failure_count` 與 `last_error` 都如實記錄——「剛剛有一次失敗」
    這個事實不該被隱藏，只是不足以宣告系統降級。
    """
    kind = _classify_error(exc)
    with _STATE.lock:
        _STATE.failure_count += 1
        _STATE.consecutive_failures += 1
        _STATE.last_error = f"{type(exc).__name__}: {exc}"[:300]

        tolerated = kind == "network" and _STATE.consecutive_failures < NETWORK_FAILURE_TOLERANCE
        if tolerated:
            # 狀態不變（維持 live/unknown），但錯誤已記錄，日誌也會留一筆。
            should_broadcast = False
        else:
            should_broadcast = _STATE.reachable is not False
            _STATE.reachable = False
            _STATE.last_error_kind = kind

    if tolerated:
        logger.warning("Bedrock 呼叫失敗（%s，第 %d 次，尚未判定降級）：%s",
                       kind, _STATE.consecutive_failures, exc)
        return

    if should_broadcast:
        logger.warning("Bedrock 轉為不可用（%s）：%s", kind, exc)
        _broadcast_status()


def probe(force: bool = False) -> bool:
    """真的送一次最小請求驗證 Bedrock 可用。回傳是否成功。

    `USE_BEDROCK=false` 時直接回 False 且不送請求——保底模式下送出請求違反
    `00-tech-stack.md` §6，而且那個模式本來就預期不用 LLM，不算「失敗」。

    Args:
        force: True 時即使 `USE_BEDROCK=false` 也送出請求（給 preflight 用）。
    """
    from src.llm import bedrock_enabled, get_model_id, invoke_converse

    if not bedrock_enabled() and not force:
        with _STATE.lock:
            _STATE.reachable = None
            _STATE.last_error = "USE_BEDROCK=false（保底模式，未驗證）"
            _STATE.last_error_kind = None
        return False

    model_id = get_model_id()
    try:
        # max_tokens=1：只要拿得到回應就代表這條路通了，不需要真的生成內容。
        # 成本可以忽略，但驗到的東西跟一次完整呼叫一樣多（憑證、權限、模型存在）。
        #
        # 成敗**不在這裡記錄**——`llm.invoke_converse()` 內部已經會呼叫
        # `record_success`／`record_failure`。這裡再記一次的話 `success_count`
        # 會變成 2（實測啟動後就是這個數字），統計就不再是「真實呼叫次數」。
        invoke_converse(
            "你是一個健康檢查探針，只回答 OK。",
            "ping",
            max_tokens=1,
            temperature=0.0,
            timeout_s=PROBE_TIMEOUT_S,
            model_id=model_id,
        )
    except Exception:  # noqa: BLE001 - 探測失敗是預期情境之一，不能往上拋
        return False

    return True


def get_status() -> dict[str, Any]:
    """供 `/api/health`、Dashboard KPI、狀態橫幅共用的狀態快照。"""
    from src.llm import bedrock_enabled, get_model_id, get_region, get_report_model_id

    with _STATE.lock:
        reachable = _STATE.reachable
        payload = {
            "enabled": bedrock_enabled(),
            "reachable": reachable,
            "region": get_region(),
            "configured_model_id": get_model_id(),
            "configured_report_model_id": get_report_model_id(),
            "active_model_id": _STATE.last_model_id,
            "last_ok_at": _STATE.last_ok_at.isoformat() if _STATE.last_ok_at else None,
            "last_error": _STATE.last_error,
            "last_error_kind": _STATE.last_error_kind,
            "last_latency_ms": _STATE.last_latency_ms,
            "success_count": _STATE.success_count,
            "failure_count": _STATE.failure_count,
        }

    payload["mode"] = _derive_mode(payload)
    payload["message"] = _derive_message(payload)
    return payload


def _derive_mode(status: dict) -> str:
    """三態：live（驗證過可用）／degraded（確定不可用）／unknown（還沒驗）。

    比原本的 live/degraded 二分多一個 unknown，是因為「還沒驗證」被歸進哪一邊
    都是說謊：歸 live 是原本那個 bug，歸 degraded 又會讓剛啟動的系統看起來壞掉。
    """
    if not status["enabled"]:
        return "degraded"
    if status["reachable"] is True:
        return "live"
    if status["reachable"] is False:
        return "degraded"
    return "unknown"


def _derive_message(status: dict) -> str:
    """給人看的一句話。憑證類錯誤要講得出「該做什麼」。"""
    mode = status["mode"]
    if mode == "unknown":
        return "正在確認 Bedrock 連線…"
    if mode == "live":
        model = status["active_model_id"] or status["configured_model_id"]
        return f"Bedrock 連線正常（{model}）"

    if not status["enabled"]:
        return "保底模式（USE_BEDROCK=false）：規則、路網、ETE 照常，文字改用固定模板"

    kind = status["last_error_kind"]
    if kind == "credential":
        return "AWS 憑證失效——請更新憑證後重啟；目前所有文字改用固定模板"
    if kind == "model":
        return f"模型不可用（{status['configured_model_id']}）——請檢查 BEDROCK_MODEL_ID"
    return "Bedrock 連線異常，已自動降級為固定模板（規則與數值不受影響）"


def _broadcast_status() -> None:
    """把狀態變化推給前端（`chat.system_status.v1`）。

    這個 message_type 從專案初期就定義在 `models.py`、前端 `ws.js` 也接好了
    `updateStatusBanner()`，但**後端從來沒有廣播過**——狀態橫幅這個功能等於
    不存在。這裡把它接上。

    走 `async_bridge` 是因為呼叫端多半在工作執行緒（決策週期、W1 對話都跑在
    `asyncio.to_thread` 底下），不能直接 `ensure_future`。
    """
    if _broadcaster is None:
        return
    try:
        from src.async_bridge import dispatch

        status = get_status()
        dispatch(_broadcaster({
            "message_type": "chat.system_status.v1",
            "payload": status,
        }))
    except Exception:  # noqa: BLE001 - 推播失敗不影響主流程
        logger.debug("系統狀態推播失敗", exc_info=True)


def reset() -> None:
    """測試輔助：回到剛啟動的狀態。"""
    global _broadcaster
    with _STATE.lock:
        _STATE.reachable = None
        _STATE.last_ok_at = None
        _STATE.last_error = None
        _STATE.last_error_kind = None
        _STATE.last_model_id = None
        _STATE.last_latency_ms = None
        _STATE.success_count = 0
        _STATE.failure_count = 0
    _broadcaster = None
