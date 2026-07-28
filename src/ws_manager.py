"""WebSocket 連線管理與廣播。參考 spec：`.kiro/specs/m5-api-orchestrator-dashboard/design.md`
第五節（[2026-07-28更正] 廣播時機從4處補齊為7處，見該節說明）。

本檔只管連線與送出，**不判斷該不該推播、什麼時候推播**——那是 orchestrator.py
（各觸發時機見 04-system-architecture.md §5 總表）的責任。
"""

from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        raise NotImplementedError("見 m5-api-orchestrator-dashboard/design.md 第五節")

    def disconnect(self, websocket: WebSocket) -> None:
        """對不存在的連線是無操作，重複移除安全。"""
        self._active.discard(websocket)

    async def broadcast(self, envelope: dict) -> int:
        """逐一送出，任一連線送出時拋例外即從 set 移除並繼續其餘連線；
        回傳成功送達數。連線集合為空時直接回 0，不視為錯誤。
        """
        raise NotImplementedError("見 m5-api-orchestrator-dashboard/design.md 第五節")
