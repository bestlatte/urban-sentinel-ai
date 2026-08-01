"""回歸測試：決策週期不得阻塞 event loop。

實測症狀（2026-08-01 回報）
--------------------------
注入事件後，畫面上的模擬時鐘會停住約 15 秒，等建議書出來才恢復。

成因是 `orchestrator.handle_incident()` 雖然宣告成 `async def`，裡面卻只有 A2
規劃器包了 `asyncio.to_thread`，其餘全是同步阻塞呼叫——其中
`GATEWAY.generate_report()` 是一次 15~20 秒的 Bedrock 往返。那段期間
`main.py::_simulation_tick_loop` 的 `await asyncio.sleep(1)` 完全排不到執行，
WebSocket 推播也一起卡住。

為什麼要用「計數協程」而不是量時間
----------------------------------
單純量 `handle_incident` 的耗時證明不了任何事——阻塞與否，總耗時都一樣。
要驗證的是「**這段期間 event loop 還能不能跑別的東西**」，所以開一個每 10ms
遞增一次的協程，跑完之後看它前進了幾格。這正是模擬時鐘在真實情境下的處境。

保底模式下真正的 `generate_report()` 只要幾毫秒，測不出差別，所以這裡用一個
會 `time.sleep()` 的假 Gateway 把「慢」這件事明確做出來——被測的是編排層有沒有
讓出 loop，不是報告產生器本身多快。
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import orchestrator
from src.models import EteEstimate, Incident, IncidentSeverity, Notification

BLOCKING_SECONDS = 0.6
"""假 Gateway 裡 generate_report 的「LLM 耗時」。

刻意取 0.6 秒而不是 15 秒：足以讓 ticker 累積出明確差距（60 格 vs 0~1 格），
又不會讓測試套件變慢。阻塞與否是**質性**差異，不需要真的等 15 秒才看得出來。
"""

TICK_INTERVAL = 0.01


class SlowReportGateway:
    """把真實 Gateway 包一層，只讓 generate_report 變慢。

    其餘方法一律轉發給真的 Gateway——這樣測到的是真實的編排流程，
    不是一個跟正式路徑無關的假物件。
    """

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate_report(self, *args, **kwargs):
        time.sleep(BLOCKING_SECONDS)  # 模擬 Bedrock 往返
        return "【交控建議書】測試用", Notification(zh="測試")


@pytest.fixture
def slow_gateway():
    if orchestrator.GATEWAY is None:
        orchestrator.GATEWAY = orchestrator.build_gateway()
    original = orchestrator.GATEWAY
    orchestrator.GATEWAY = SlowReportGateway(original)
    try:
        yield orchestrator.GATEWAY
    finally:
        orchestrator.GATEWAY = original
        orchestrator.reset()


def _acc001(gateway) -> Incident:
    bundle = gateway.load_data()
    return next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")


async def _count_ticks(stop_event: asyncio.Event) -> int:
    """模擬 `_simulation_tick_loop`：每 TICK_INTERVAL 秒推進一格。"""
    ticks = 0
    while not stop_event.is_set():
        await asyncio.sleep(TICK_INTERVAL)
        ticks += 1
    return ticks


def test_handle_incident_does_not_block_event_loop(slow_gateway):
    """決策週期跑滿 BLOCKING_SECONDS 期間，背景協程必須持續前進。"""

    async def scenario():
        stop = asyncio.Event()
        ticker = asyncio.create_task(_count_ticks(stop))

        started = time.perf_counter()
        await orchestrator.handle_incident(_acc001(slow_gateway))
        elapsed = time.perf_counter() - started

        stop.set()
        ticks = await ticker
        return elapsed, ticks

    elapsed, ticks = asyncio.run(scenario())

    # 前提檢查：慢 Gateway 真的讓週期變慢了，否則下面的斷言沒有意義
    assert elapsed >= BLOCKING_SECONDS, "假 Gateway 沒有生效，這個測試證明不了任何事"

    # 完全不阻塞的話 ticker 應該前進 elapsed/TICK_INTERVAL 格（0.6s → ~60 格）。
    # 抓 50% 當門檻：留給排程抖動與其餘同步小運算的餘裕，但阻塞時 ticks 會是
    # 個位數，離門檻很遠，不會誤判。
    expected = elapsed / TICK_INTERVAL
    assert ticks >= expected * 0.5, (
        f"event loop 被阻塞：{elapsed:.2f} 秒內背景協程只前進 {ticks} 格，"
        f"預期至少 {expected * 0.5:.0f} 格"
    )


def test_handle_user_query_runs_off_the_event_loop():
    """`main.py::what_if()` 必須用 to_thread 呼叫 handle_user_query。

    這個函式內含最長 60 秒（`llm.AGENT_TIMEOUT_S`）的阻塞 Bedrock 呼叫，直接在
    async 端點裡呼叫會讓整個伺服器停擺——包含模擬時鐘、WebSocket 推播、
    以及本來就該即時回應的 loading 進度推播。

    用原始碼斷言而不是行為斷言：真的跑一次 W1 需要 Bedrock 憑證，而這條規則
    是結構性的（「有沒有讓出 loop」），看得出來就夠了。
    """
    import inspect

    import main

    source = inspect.getsource(main.what_if)
    assert "asyncio.to_thread" in source, "what_if 必須用 asyncio.to_thread 呼叫 handle_user_query"
    assert "orchestrator.handle_user_query" in source
