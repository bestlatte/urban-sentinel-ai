"""處理過程中透過 WebSocket 逐步推送 loading 進度。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第十一節。
推播訊息要套 Message Envelope，message_type 用 `chat.loading_start.v1` /
`chat.loading_step.v1`（不是裸字串，見 `F6-chat-ui/design.md` 已修正版）。

實作方案B（兩段式）：Strands Agent 不支援 streaming tool call 事件，
退化為「開始 loading → 全部完成」兩段。
"""

from __future__ import annotations

from typing import Callable, Awaitable

LOADING_STEPS = [
    "解析問題意圖",
    "檢索 SOP 條款",
    "呼叫決策模組",
    "計算 ETE",
    "組合回覆",
]


async def broadcast_loading_start(
    ws_broadcaster: Callable[[dict], Awaitable[int]] | None,
    correlation_id: str,
) -> None:
    """推播 loading 開始（方案B第一段）。ws_broadcaster 不可用時靜默跳過。"""
    if ws_broadcaster is None:
        return
    try:
        await ws_broadcaster({
            "message_type": "chat.loading_start.v1",
            "payload": {
                "correlation_id": correlation_id,
                "steps": LOADING_STEPS,
                "current_step": 0,
            },
        })
    except Exception:
        pass  # 推播失敗不影響主流程


async def broadcast_loading_complete(
    ws_broadcaster: Callable[[dict], Awaitable[int]] | None,
    correlation_id: str,
) -> None:
    """推播 loading 完成（方案B第二段）。ws_broadcaster 不可用時靜默跳過。"""
    if ws_broadcaster is None:
        return
    try:
        await ws_broadcaster({
            "message_type": "chat.loading_step.v1",
            "payload": {
                "correlation_id": correlation_id,
                "steps": LOADING_STEPS,
                "current_step": len(LOADING_STEPS),
                "all_done": True,
            },
        })
    except Exception:
        pass  # 推播失敗不影響主流程


def broadcast_loading_start_sync(
    ws_broadcaster: Callable[[dict], Awaitable[int]] | None,
    correlation_id: str,
) -> None:
    """同步版本：在非 async 上下文中使用。

    [2026-08-01 改用 async_bridge]
    原本是 `asyncio.get_event_loop()` + `ensure_future`，那假設呼叫端人在
    event loop 執行緒上。`main.py::what_if()` 改成 `asyncio.to_thread` 之後
    整條 W1 流程都跑在工作執行緒，該假設不成立——`get_event_loop()` 會拋
    `RuntimeError`，被外層 `except: pass` 吃掉，**進度條推播靜默消失**。

    用 `dispatch_and_wait` 而不是 `dispatch`：loading 開始必須確定先於答案
    抵達前端，射後不理的話兩者會賽跑。
    """
    if ws_broadcaster is None:
        return
    from src.async_bridge import dispatch_and_wait

    dispatch_and_wait(broadcast_loading_start(ws_broadcaster, correlation_id))


def broadcast_loading_complete_sync(
    ws_broadcaster: Callable[[dict], Awaitable[int]] | None,
    correlation_id: str,
) -> None:
    """同步版本：在非 async 上下文中使用。理由同 `broadcast_loading_start_sync`。"""
    if ws_broadcaster is None:
        return
    from src.async_bridge import dispatch

    # 完成訊號不需要等——後面沒有順序相依的推播了，REST 回應本身就是終點。
    dispatch(broadcast_loading_complete(ws_broadcaster, correlation_id))
