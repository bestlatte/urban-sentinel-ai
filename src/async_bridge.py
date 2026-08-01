"""從同步程式碼把 coroutine 送回主 event loop 執行。

為什麼需要這個檔案
------------------
[2026-08-01] `main.py::what_if()` 改用 `asyncio.to_thread()` 呼叫
`orchestrator.handle_user_query()`（不改的話 60 秒的 Bedrock 呼叫會凍結整個
伺服器，見該處註解）。這個改動讓底下所有推播程式碼的前提整個翻掉：

原本的寫法（`agent/loading.py`、`agent/whatif_agent.py`）是

    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.ensure_future(coro)

這假設「我雖然是同步函式，但我人在 event loop 的執行緒上」。搬進工作執行緒後
這個假設不成立：Python 3.12 的 `asyncio.get_event_loop()` 在沒有執行中 loop 的
非主執行緒會直接拋 `RuntimeError`，而那些呼叫點全部包在 `except: pass` 裡——
**推播會靜默消失，一行日誌都沒有**。

（就算沒拋例外也一樣不會動：`ensure_future` 只能把工作排到「當前執行緒的」
loop 上，工作執行緒根本沒有 loop。）

正確做法是 `asyncio.run_coroutine_threadsafe(coro, loop)`，但它需要一個明確的
loop 物件參照。本模組就是存那個參照的地方：`main.py` 在 startup 時登記一次，
之後任何執行緒的任何同步程式碼都能靠 `dispatch()` 把推播送出去。

刻意不做的事
------------
不管推播內容、不管重試、不管順序保證——那些是各呼叫端的職責。本模組只回答
一個問題：「這個 coroutine 該丟到哪裡跑」。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Coroutine

logger = logging.getLogger(__name__)

_MAIN_LOOP: asyncio.AbstractEventLoop | None = None
"""FastAPI 行程的主 event loop。由 `set_main_loop()` 在 startup 時登記。

為 `None` 代表「不在 web 行程裡」（單元測試、CLI 腳本、AgentCore Runtime 的
非同步入口）。這是合法狀態，不是錯誤——`dispatch()` 遇到 None 會安靜跳過，
因為那些情境本來就沒有 WebSocket 客戶端在等推播。
"""


def set_main_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """登記主 event loop。`main.py` 的 startup handler 呼叫一次。

    不傳參數時取當前執行中的 loop（在 startup handler 裡就是主 loop）。
    """
    global _MAIN_LOOP
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("set_main_loop() 在沒有執行中 loop 的情境被呼叫，略過登記")
            return
    _MAIN_LOOP = loop


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _MAIN_LOOP


def dispatch(coro: Coroutine) -> None:
    """射後不理地執行 `coro`，不論呼叫端在哪個執行緒。

    三種情境都要正確處理：

    1. **呼叫端就在 event loop 執行緒上**（例如 `main.py` 的其他同步小函式）
       → `create_task()`。
    2. **呼叫端在工作執行緒**（`asyncio.to_thread` 底下的整條 W1 流程）
       → `run_coroutine_threadsafe()` 送回主 loop。
    3. **根本沒有 web 行程**（單元測試）
       → 關掉 coroutine 並安靜返回。**必須顯式 `close()`**，否則 Python 會噴
       `RuntimeWarning: coroutine was never awaited`，測試輸出被雜訊淹沒。

    失敗只記 debug 不拋例外——推播是加值資訊，任何情況下都不該讓它中斷主流程。
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        running.create_task(coro)
        return

    loop = _MAIN_LOOP
    if loop is None or loop.is_closed():
        coro.close()  # 見 docstring 第 3 點
        return

    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception:  # noqa: BLE001
        logger.debug("推播派送失敗", exc_info=True)
        coro.close()


def dispatch_and_wait(coro: Coroutine, timeout: float = 2.0) -> None:
    """同 `dispatch()`，但在工作執行緒時**等推播真的送出去**才返回。

    用在「順序有意義」的推播上——loading 開始必須先於答案抵達，射後不理的話
    兩者會賽跑，實測會出現進度條在答案之後才冒出來。等待上限預設 2 秒，
    純粹是防呆（一次 WebSocket send 是毫秒級），逾時就放棄不重試。

    在 event loop 執行緒上無法等待（等於自己 deadlock），退回 `dispatch()`。
    """
    try:
        asyncio.get_running_loop()
        dispatch(coro)
        return
    except RuntimeError:
        pass

    loop = _MAIN_LOOP
    if loop is None or loop.is_closed():
        coro.close()
        return

    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.result(timeout=timeout)
    except Exception:  # noqa: BLE001
        logger.debug("推播派送（等待版）失敗或逾時", exc_info=True)
