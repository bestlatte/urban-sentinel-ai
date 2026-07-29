"""FastAPI 入口：四個 REST 端點 + /ws + 掛載 frontend/ 靜態檔（單一 Server）。

參考 spec：`.kiro/specs/m5-api-orchestrator-dashboard/design.md` 第3節「main.py：端點與payload對應」；
固定 API 表面見 `.kiro/steering/00-tech-stack.md` §4，**不得擴充端點**。

`POST /api/what-if` 依問題類型回傳 `WhatIfResult` 或 `TraceAnswer`，見
`.kiro/steering/04-system-architecture.md` §5 三分支路由規則，不要誤以為這個
端點永遠回傳同一種形狀。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from src import orchestrator
from src.ws_manager import ConnectionManager

app = FastAPI()
ws_manager = ConnectionManager()

# [2026-07-28總架構師補充：架構完整性修正] 原本這裡寫 `GATEWAY = build_gateway()`
# 建立的是 main.py 自己的區域變數，跟 `src/orchestrator.py` 模組層級的 `GATEWAY`
# （orchestrator.py 內的函式實際讀取的那個）是兩個不同的名字空間——orchestrator.py
# 的 handle_incident/handle_trigger_batch 永遠只會看到 None。改成直接賦值給
# orchestrator 模組本身，確保只有一份 GATEWAY 實例。
orchestrator.GATEWAY = orchestrator.build_gateway()


@app.on_event("startup")
async def _startup_rule_scan():
    """啟動時跑一次全量規則評估，觸發 handle_trigger_batch。"""
    global _last_traffic_level
    try:
        bundle = orchestrator.GATEWAY.load_data()
        sensing = orchestrator.GATEWAY.evaluate_rules(bundle, incident=None)

        # 推播 rules.evaluated.v1（每次規則評估後都推，讓 F1 即時更新）
        await ws_manager.broadcast({
            "message_type": "rules.evaluated.v1",
            "payload": sensing.model_dump(mode="json"),
        })

        # 找出命中的 SOP 條款，組成 batch
        triggered = []
        seen_sections = set()
        for hit in sensing.rule_hits:
            section = hit.clause_id.replace("SOP-", "")
            if section not in seen_sections:
                seen_sections.add(section)
                triggered.append({"section": int(section), "clause_id": hit.clause_id})
        if triggered:
            orchestrator.handle_trigger_batch(triggered)
            logger.info(f"啟動時規則掃描完成：{len(triggered)} 條規則觸發")
        else:
            logger.info("啟動時規則掃描完成：無規則觸發")

        # 同步 _last_traffic_level，讓背景迴圈第一輪不會誤判為「新轉換」
        _last_traffic_level = sensing.traffic_level if sensing.traffic_level != "normal" else None
    except Exception as e:
        logger.warning(f"啟動時規則掃描失敗（不影響核心功能）: {e}")


_RULE_MONITOR_INTERVAL_SECONDS = 10
"""背景監測輪詢間隔，落在架構圖規定的 5~15 秒區間內（見
`.kiro/specs/architecture-reference/模組架構圖_整合版.md` 情境A：
「後端每 5~15 秒推進一次並以 WebSocket 主動推播」）。"""

_last_traffic_level: str | None = None
"""上一輪背景監測算出的全市交通等級（"A"/"B"/None），供跟這一輪比較找出轉換。
只有 `_periodic_rule_monitor` 這個背景迴圈會讀寫，不對外暴露。"""


@app.on_event("startup")
async def _start_periodic_rule_monitor():
    """啟動背景週期性監測任務。"""
    import asyncio
    asyncio.create_task(_periodic_rule_monitor())


async def _periodic_rule_monitor() -> None:
    """背景無限迴圈：每 _RULE_MONITOR_INTERVAL_SECONDS 秒重跑全量規則評估，
    只在等級轉換時才推播。
    """
    import asyncio
    global _last_traffic_level

    while True:
        await asyncio.sleep(_RULE_MONITOR_INTERVAL_SECONDS)

        try:
            bundle = orchestrator.GATEWAY.load_data()
            sensing = orchestrator.GATEWAY.evaluate_rules(bundle, incident=None)

            # 推播 rules.evaluated.v1（每次規則評估後都推，讓 F1 即時更新）
            await ws_manager.broadcast({
                "message_type": "rules.evaluated.v1",
                "payload": sensing.model_dump(mode="json"),
            })

            current_level = sensing.traffic_level if sensing.traffic_level != "normal" else None

            if current_level == _last_traffic_level:
                continue  # 沒有變化，不做任何事

            # 等級轉換
            logger.info(f"背景監測偵測等級轉換: {_last_traffic_level} → {current_level}")

            # 組 triggered batch 呼叫 handle_trigger_batch
            triggered = []
            seen_sections = set()
            for hit in sensing.rule_hits:
                section = hit.clause_id.replace("SOP-", "")
                if section not in seen_sections:
                    seen_sections.add(section)
                    triggered.append({"section": int(section), "clause_id": hit.clause_id})

            if triggered:
                orchestrator.handle_trigger_batch(triggered)

            # 推播 decision.alert.v1（升級時）
            if current_level in ("A", "B"):
                await ws_manager.broadcast({
                    "message_type": "decision.alert.v1",
                    "payload": {
                        "level": current_level,
                        "description": "背景監測偵測到全市交通等級變化",
                        "ete_minutes": None,
                    },
                })

            # 推播 dashboard.updated.v1
            await ws_manager.broadcast({
                "message_type": "dashboard.updated.v1",
                "payload": {"level": current_level},
            })

            _last_traffic_level = current_level

        except Exception as e:
            logger.warning(f"背景規則監測失敗: {e}")

# frontend/ 以 StaticFiles(html=True) 掛在 /，API 前綴 /api 與 /ws 不會被靜態路由吃掉。
app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")
# data/ 掛載供前端 fetch display_geometry.json（僅 SVG 顯示用，不參與演算）
app.mount("/data", StaticFiles(directory="data"), name="data")


@app.exception_handler(Exception)
async def unified_exception_handler(request: Request, exc: Exception):
    """三個 Envelope 端點共用例外處理器，把例外收斂成 status="error"。
    GET /api/health 不套用此處理器（不使用 Envelope）。
    """
    import asyncio

    # /api/health 不走 Envelope 格式
    if request.url.path == "/api/health":
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(exc)},
        )

    # 錯誤碼映射
    if isinstance(exc, ValidationError):
        code = "VALIDATION_ERROR"
        field = None
        try:
            field = exc.errors()[0].get("loc", [None])[-1]
        except (IndexError, AttributeError):
            pass
        errors = [{"code": code, "message": str(exc), "field": field}]
    elif isinstance(exc, ValueError):
        # DATA_NOT_FOUND 情境（event_id 不存在等）
        msg = str(exc)
        if "不存在" in msg or "not found" in msg.lower() or "DATA_NOT_FOUND" in msg:
            code = "DATA_NOT_FOUND"
        else:
            code = "VALIDATION_ERROR"
        errors = [{"code": code, "message": msg}]
    elif isinstance(exc, asyncio.TimeoutError):
        errors = [{"code": "TIMEOUT", "message": "操作逾時"}]
    elif isinstance(exc, NotImplementedError):
        errors = [{"code": "INTERNAL_ERROR", "message": f"功能尚未實作: {exc}"}]
    else:
        errors = [{"code": "INTERNAL_ERROR", "message": str(exc)}]

    return JSONResponse(
        status_code=200,
        content={"status": "error", "errors": errors},
    )


@app.get("/api/dashboard")
async def get_dashboard():
    """回傳 message_type=dashboard.updated.v1 的 DashboardPayload。"""
    from datetime import datetime, timezone, timedelta
    from src.models import DashboardPayload, KpiSummary, DataProvenance

    state = orchestrator.get_global_state()
    bundle = orchestrator.GATEWAY.load_data()

    # KPI 計算
    active_incidents = list(state.active_incidents.values())
    active_count = len(active_incidents)

    # 目前最高應變等級
    current_level = None
    if active_incidents:
        for record in active_incidents:
            if record.decision_result and record.decision_result.level:
                if record.decision_result.level == "A":
                    current_level = "A"
                    break
                elif record.decision_result.level == "B" and current_level != "A":
                    current_level = "B"

    # 全路網平均飽和度
    saturations = [t.saturation_score for t in bundle.traffic if t.saturation_score is not None]
    avg_sat = sum(saturations) / len(saturations) if saturations else None

    # SOP-6 觸發站點數
    from src.rules import get_roaming_ratio
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz=tz)
    all_stations = {c.station_id for c in bundle.crowd}
    multilingual_count = sum(
        1 for sid in all_stations
        if (r := get_roaming_ratio(bundle, sid, now)) is not None and r >= 0.30
    )

    # 系統模式
    import os
    use_bedrock = os.getenv("USE_BEDROCK", "true").lower() == "true"
    system_mode = "live" if use_bedrock else "degraded"

    kpis = KpiSummary(
        crowd_data_classification=DataProvenance.PROVIDED,
        active_incident_count=active_count,
        current_level=current_level,
        average_saturation=round(avg_sat, 4) if avg_sat is not None else None,
        multilingual_alert_count=multilingual_count,
        system_mode=system_mode,
    )

    # 活躍事件清單
    active_incident_models = [r.incident for r in active_incidents]

    payload = DashboardPayload(
        kpis=kpis,
        active_incidents=active_incident_models,
        as_of=now,
    )

    return JSONResponse(content={
        "status": "ok",
        "message_type": "dashboard.updated.v1",
        "payload": payload.model_dump(mode="json"),
        "traffic_samples": [
            {"timestamp": t.timestamp.isoformat(), "saturation_score": t.saturation_score, "segment_id": t.segment_id}
            for t in bundle.traffic
            if t.saturation_score is not None
        ],
    })


@app.post("/api/incidents/evaluate")
async def evaluate_incident(body: dict):
    """body={"event_id": str}；呼叫 handle_incident()，回傳 decision.completed.v1。"""
    event_id = body.get("event_id")
    if not event_id:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "VALIDATION_ERROR", "message": "event_id 為必填"}],
        })

    # 從 bundle 找對應事件
    bundle = orchestrator.GATEWAY.load_data()
    matched = [i for i in bundle.incidents if i.event_id == event_id]
    if not matched:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "DATA_NOT_FOUND", "message": f"event_id '{event_id}' 不存在"}],
        })

    incident = matched[0]

    # 廣播 decision.cycle_start.v1（週期開始，不帶 trace_id — 真正的 trace_id
    # 由 handle_incident 內部產生，避免格式對不上）
    await ws_manager.broadcast({
        "message_type": "decision.cycle_start.v1",
        "payload": {"triggered_by": [event_id]},
    })

    decision_result = await orchestrator.handle_incident(incident, ws_broadcaster=ws_manager.broadcast)
    payload_json = decision_result.model_dump(mode="json")

    # 廣播 decision.alert.v1（若等級為 A 或 B）
    if decision_result.level in ("A", "B"):
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": decision_result.level,
                "description": incident.description,
                "ete_minutes": decision_result.ete.minutes if decision_result.ete else None,
            },
        })

    # 廣播 decision.completed.v1
    await ws_manager.broadcast({
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })

    # 廣播 dashboard.updated.v1（決策完成後現況變動）
    await ws_manager.broadcast({
        "message_type": "dashboard.updated.v1",
        "payload": {"event_id": event_id, "level": decision_result.level},
    })

    return JSONResponse(content={
        "status": "ok",
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })


@app.post("/api/what-if")
async def what_if(body: dict):
    """三分支路由：前瞻假設 → W1、回溯追問 → M4B、無週期 → 固定文字。"""
    from dataclasses import asdict

    session_id = body.get("session_id", "")
    content = body.get("content", "")
    current_trace_id = body.get("current_trace_id")
    correlation_id = body.get("correlation_id", session_id)

    if not session_id or not content:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "VALIDATION_ERROR", "message": "session_id 與 content 為必填"}],
        })

    result = orchestrator.handle_user_query(
        question=content,
        current_trace_id=current_trace_id,
        session_id=session_id,
        correlation_id=correlation_id,
        ws_broadcaster=ws_manager.broadcast,
    )

    message_type = result["message_type"]
    payload = result["payload"]

    # W1Response 是 dataclass，需要轉成 dict
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)

    return JSONResponse(content={
        "status": "ok",
        "message_type": message_type,
        "payload": payload,
    })


@app.get("/api/health")
async def health():
    """不使用 Envelope。回傳 {status, use_bedrock, gateway_mode}。"""
    import os
    from src.orchestrator import StubGateway, LiveGateway

    use_bedrock = os.getenv("USE_BEDROCK", "true").lower() == "true"

    gw = orchestrator.GATEWAY
    if isinstance(gw, StubGateway):
        gateway_mode = "stub"
    elif isinstance(gw, LiveGateway):
        gateway_mode = "live"
    else:
        gateway_mode = "mixed"

    return {"status": "ok", "use_bedrock": use_bedrock, "gateway_mode": gateway_mode}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """單向推播，收到的內容大部分丟棄。
    例外：chat.clear_session.v1 會真的處理（W2 session 清除）。
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # 嘗試解析 clear_session
            try:
                import json
                msg = json.loads(raw)
                if msg.get("message_type") == "chat.clear_session.v1":
                    session_id = msg.get("payload", {}).get("session_id")
                    if session_id:
                        from src.session.session_manager import clear_session
                        clear_session(session_id)
                        await websocket.send_json({
                            "message_type": "chat.session_cleared.v1",
                            "payload": {"session_id": session_id},
                        })
            except (json.JSONDecodeError, KeyError):
                pass  # 非 JSON 或格式不對，丟棄
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
