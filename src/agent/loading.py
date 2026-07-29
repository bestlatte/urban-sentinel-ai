"""處理過程中透過 WebSocket 逐步推送 loading 進度。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第十一節。
推播訊息要套 Message Envelope，message_type 用 `chat.loading_start.v1` /
`chat.loading_step.v1`（不是裸字串，見 `F6-chat-ui/design.md` 已修正版）。

實作方案B（兩段式）：Strands Agent 不支援 streaming tool call 事件，
退化為「開始 loading → 全部完成」兩段。
"""

from __future__ import annotations

import asyncio
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
    """同步版本：在非 async 上下文中使用。"""
    if ws_broadcaster is None:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已經跑著的 event loop 裡不能用 run_until_complete
            # 這種情況下只能跳過（process_whatif_request 是同步函式被 async 端點呼叫）
            asyncio.ensure_future(broadcast_loading_start(ws_broadcaster, correlation_id))
        else:
            loop.run_until_complete(broadcast_loading_start(ws_broadcaster, correlation_id))
    except Exception:
        pass


def broadcast_loading_complete_sync(
    ws_broadcaster: Callable[[dict], Awaitable[int]] | None,
    correlation_id: str,
) -> None:
    """同步版本：在非 async 上下文中使用。"""
    if ws_broadcaster is None:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_loading_complete(ws_broadcaster, correlation_id))
        else:
            loop.run_until_complete(broadcast_loading_complete(ws_broadcaster, correlation_id))
    except Exception:
        pass
