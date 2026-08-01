"""`/api/dashboard` 的煙霧測試。

[2026-08-02] 這支端點原本**一個測試都沒有**，於是一個變數改名就讓整個
Dashboard 掛掉，而 326 個測試全部通過：

    # 統一系統時間時，把 `now = datetime.now(tz)` 改名成 `as_of = clock.now()`，
    # 漏掉函式尾端的 `DashboardPayload(as_of=now)`
    → {"status": "error", "message": "name 'now' is not defined"}

前端每 8 秒輪詢一次這支（`ws.js::_startPollingFallback`），也在 WebSocket
`dashboard.updated.v1` 之外當退路，它掛掉等於首頁的 KPI 全部停止更新。
端點層的煙霧測試很便宜，缺了它代價是這種只有在瀏覽器打開時才發現的錯。
"""

from __future__ import annotations

import os

os.environ.setdefault("USE_BEDROCK", "false")

from fastapi.testclient import TestClient

from main import app


def test_dashboard_returns_ok():
    """最基本的一件事：這支端點不能回 error。"""
    with TestClient(app) as client:
        body = client.get("/api/dashboard").json()

    assert body["status"] == "ok", body.get("errors")
    assert body["message_type"] == "dashboard.updated.v1"


def test_dashboard_payload_has_kpis_and_as_of():
    """KPI 與評估時刻都要有——前端 `renderKpis()` 直接讀這些欄位。"""
    with TestClient(app) as client:
        payload = client.get("/api/dashboard").json()["payload"]

    assert payload["as_of"], "缺少 as_of，前端無從知道這份 KPI 是哪個時刻的"

    kpis = payload["kpis"]
    for field in (
        "active_incident_count",
        "current_level",
        "multilingual_alert_count",
        "system_mode",
    ):
        assert field in kpis, f"KPI 缺少 {field}"


def test_dashboard_as_of_follows_simulator(monkeypatch):
    """模擬器在跑時，Dashboard 的評估時刻要跟著模擬器走。

    這是「所有系統時間統一模擬器」的一部分：`as_of` 同時決定 SOP-6 多語通報
    站點數要查哪個時刻的漫遊比率，拿真實時間算出來的是別的時段的數字。
    """
    from datetime import datetime, timedelta, timezone

    from src import clock

    sim = datetime(2026, 5, 20, 22, 10, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(clock, "simulation_time", lambda: sim)

    with TestClient(app) as client:
        payload = client.get("/api/dashboard").json()["payload"]

    assert payload["as_of"].startswith("2026-05-20T22:10")
