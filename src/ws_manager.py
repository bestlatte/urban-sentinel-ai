"""WebSocket 連線管理與廣播。參考 spec：`.kiro/specs/m5-api-orchestrator-dashboard/design.md`
第五節（廣播時機從4處補齊為7處）。

本檔只管連線與送出，**不判斷該不該推播、什麼時候推播**——那是 orchestrator.py
（各觸發時機見 04-system-architecture.md §5 總表）的責任。
"""

from __future__ import annotations

import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """接受 WebSocket 連線並加入活躍集合。"""
        await websocket.accept()
        self._active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """對不存在的連線是無操作，重複移除安全。"""
        self._active.discard(websocket)

    async def broadcast(self, envelope: dict) -> int:
        """逐一送出，任一連線送出時拋例外即從 set 移除並繼續其餘連線；
        回傳成功送達數。連線集合為空時直接回 0，不視為錯誤。
        """
        if not self._active:
            return 0

        success_count = 0
        disconnected: list[WebSocket] = []

        for ws in self._active:
            try:
                await ws.send_json(envelope)
                success_count += 1
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self._active.discard(ws)

        return success_count

    @property
    def active_count(self) -> int:
        return len(self._active)
