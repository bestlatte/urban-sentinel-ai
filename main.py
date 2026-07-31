"""FastAPI 入口：四個 REST 端點 + /ws + 掛載 frontend/ 靜態檔（單一 Server）。

參考 spec：`.kiro/specs/m5-api-orchestrator-dashboard/design.md` 第3節「main.py：端點與payload對應」；
固定 API 表面見 `.kiro/steering/00-tech-stack.md` §4，**不得擴充端點**。

`POST /api/what-if` 依問題類型回傳 `WhatIfResult` 或 `TraceAnswer`，見
`.kiro/steering/04-system-architecture.md` §5 三分支路由規則，不要誤以為這個
端點永遠回傳同一種形狀。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

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

_TZ_TAIPEI = timezone(timedelta(hours=8))

# 模擬時間狀態
_simulation_state = {
    "enabled": False,
    "current_time": None,  # datetime
    "start_time": None,    # 資料最早時間
    "end_time": None,      # 資料最晚時間
    "speed": 1,            # 1 = 即時, 60 = 1秒跑1分鐘
    "playing": False,
    "last_level": None,    # 上一次的等級，用於偵測變化
}


@app.on_event("startup")
async def _start_periodic_rule_monitor():
    """啟動背景週期性監測任務。"""
    import asyncio
    asyncio.create_task(_periodic_rule_monitor())
    asyncio.create_task(_simulation_tick_loop())  # 獨立的模擬器 tick 迴圈


async def _simulation_tick_loop() -> None:
    """模擬器專用迴圈：每 1 秒檢查是否要推進模擬時間。
    
    速度設定：speed=60 表示 1 秒推進 1 分鐘，speed=300 表示 1 秒推進 5 分鐘。
    """
    import asyncio
    
    while True:
        await asyncio.sleep(1)  # 每 1 秒 tick
        
        if not _simulation_state["enabled"] or not _simulation_state["playing"]:
            continue
        
        if not _simulation_state["current_time"]:
            continue
        
        try:
            # 推進模擬時間：1 秒推進 speed 秒（換算成分鐘）
            speed = _simulation_state.get("speed", 60)
            advance_minutes = speed / 60  # speed=60 → 1分鐘, speed=300 → 5分鐘
            _simulation_state["current_time"] += timedelta(minutes=advance_minutes)
            
            # 檢查是否超過結束時間
            if _simulation_state["end_time"] and _simulation_state["current_time"] > _simulation_state["end_time"]:
                _simulation_state["current_time"] = _simulation_state["end_time"]
                _simulation_state["playing"] = False
                await ws_manager.broadcast({
                    "message_type": "simulation.state.v1",
                    "payload": {"action": "ended", "current_time": _simulation_state["current_time"].isoformat()}
                })
                continue
            
            # 推播時間更新
            await ws_manager.broadcast({
                "message_type": "simulation.tick.v1",
                "payload": {"current_time": _simulation_state["current_time"].isoformat()}
            })
            
            # 每分鐘做一次規則評估（避免太頻繁）
            current_minute = _simulation_state["current_time"].minute
            last_eval_minute = _simulation_state.get("last_eval_minute", -1)
            
            if current_minute != last_eval_minute:
                _simulation_state["last_eval_minute"] = current_minute
                await _evaluate_and_alert_at_simtime()
                
        except Exception as e:
            logger.warning(f"模擬器 tick 失敗: {e}")


async def _evaluate_and_alert_at_simtime() -> None:
    """在模擬時間做規則評估，針對每個路段獨立追蹤等級變化並彈窗。
    
    當偵測到路段飽和時，同時檢查該路段是否為某個活躍事件的推薦路線，
    若是則觸發路線重規劃並推播 routes.updated.v1。
    """
    sim_time = _simulation_state.get("current_time")
    if not sim_time:
        return
    
    bundle = orchestrator.GATEWAY.load_data()
    
    # 初始化路段等級追蹤（如果還沒有）
    if "segment_levels" not in _simulation_state:
        _simulation_state["segment_levels"] = {}
    
    # 取得該時間點所有路段的飽和度
    from src.rules import get_saturation
    
    alerts_to_send = []
    saturated_segments = []  # 記錄本次新飽和的路段
    
    for segment in bundle.road_network:
        seg_id = segment.segment_id
        sat = get_saturation(bundle, seg_id, sim_time)
        
        if sat is None:
            continue
        
        # 判定這條路段的等級
        if sat >= 0.95:
            current_level = "A"
        elif sat >= 0.85:
            current_level = "B"
        else:
            current_level = "normal"
        
        # 跟上次的等級比較
        last_level = _simulation_state["segment_levels"].get(seg_id, "normal")
        
        if current_level != last_level:
            _simulation_state["segment_levels"][seg_id] = current_level
            
            # 只有升級到 A 或 B 才發預警（降級不發）
            if current_level in ("A", "B"):
                road_name = segment.name or seg_id
                logger.info(f"[模擬 {sim_time.strftime('%H:%M')}] {road_name} 等級變化: {last_level} → {current_level}")
                
                alerts_to_send.append({
                    "level": current_level,
                    "segment_id": seg_id,
                    "road_name": road_name,
                    "saturation": round(sat, 2),
                    "time": sim_time.strftime('%H:%M'),
                })
                saturated_segments.append(seg_id)
    
    # 發送所有路段的預警
    for alert in alerts_to_send:
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": alert["level"],
                "description": f"[{alert['time']}] {alert['road_name']} 飽和度達 {alert['saturation']}",
                "segment_id": alert["segment_id"],
                "road_name": alert["road_name"],
                "saturation": alert["saturation"],
                "ete_minutes": None,
            },
        })
    
    # ★ 新增：檢查飽和路段是否為某個活躍事件的推薦路線
    if saturated_segments:
        await _check_and_replan_affected_routes(saturated_segments, sim_time)
    
    # 推播 dashboard.updated.v1
    if alerts_to_send:
        await ws_manager.broadcast({
            "message_type": "dashboard.updated.v1",
            "payload": {"alerts": alerts_to_send},
        })


async def _check_and_replan_affected_routes(saturated_segments: list[str], as_of: datetime) -> None:
    """檢查飽和路段是否影響到活躍事件的推薦路線，若是則重規劃並推播。
    
    這是「路線動態更新」的核心邏輯：當系統偵測到某路段飽和（透過現有的
    decision.alert.v1 機制），同時檢查這個路段是不是已經被推薦為某個事件
    的替代路線——如果是，就立即重新規劃並通知前端。
    """
    state = orchestrator.get_global_state()
    saturated_set = set(saturated_segments)
    
    for event_id, record in list(state.active_incidents.items()):
        if record.decision_result is None or record.decision_result.routes is None:
            continue
        
        routes = record.decision_result.routes
        affected = False
        affected_route_type = None
        
        # 檢查主路線
        if routes.primary and routes.primary.segment_id in saturated_set:
            affected = True
            affected_route_type = "primary"
            logger.info(f"[路線監測] 事件 {event_id} 的主路線 {routes.primary.segment_id} 已飽和")
        
        # 檢查次路線
        if routes.secondary and routes.secondary.segment_id in saturated_set:
            affected = True
            if affected_route_type:
                affected_route_type = "both"
            else:
                affected_route_type = "secondary"
            logger.info(f"[路線監測] 事件 {event_id} 的次路線 {routes.secondary.segment_id} 已飽和")
        
        if not affected:
            continue
        
        # 觸發重規劃
        result = orchestrator.check_and_replan_routes(event_id, as_of)
        
        if result and result.replanned:
            # 推播 routes.updated.v1 通知前端
            await ws_manager.broadcast({
                "message_type": "routes.updated.v1",
                "payload": {
                    "event_id": event_id,
                    "reason": "ROUTE_SATURATED",
                    "affected_route": affected_route_type,
                    "old_primary": result.old_primary,
                    "new_primary": result.new_primary,
                    "old_secondary": result.old_secondary,
                    "new_secondary": result.new_secondary,
                    "invalid_reasons": result.invalid_reasons,
                    "replan_count": record.route_replan_count,
                    "time": as_of.isoformat(),
                },
            })
            
            # 同時推播更新後的完整 decision result
            if result.new_decision_result:
                await ws_manager.broadcast({
                    "message_type": "decision.completed.v1",
                    "payload": result.new_decision_result.model_dump(mode="json"),
                })


async def _periodic_rule_monitor() -> None:
    """背景無限迴圈：每 _RULE_MONITOR_INTERVAL_SECONDS 秒重跑全量規則評估。
    
    注意：
    - 模擬器時間推進改由 _simulation_tick_loop 處理
    - 非模擬模式下，因為資料是靜態歷史資料，不做等級變化預警推播
      （避免每次輪詢都因為查到同樣的歷史資料而重複彈窗）
    """
    import asyncio

    while True:
        await asyncio.sleep(_RULE_MONITOR_INTERVAL_SECONDS)
        
        # 模擬器運行中，跳過（由 _simulation_tick_loop 處理）
        if _simulation_state["enabled"]:
            continue
        
        # 非模擬模式：只做一次性的規則評估供 Dashboard 顯示，不做預警推播
        # 因為資料是靜態歷史資料，持續推播沒有意義
        try:
            bundle = orchestrator.GATEWAY.load_data()
            sensing = orchestrator.GATEWAY.evaluate_rules(bundle, incident=None)

            # 只推播 rules.evaluated.v1 讓 F1 顯示，不做 alert
            sensing_payload = sensing.model_dump(mode="json")
            await ws_manager.broadcast({
                "message_type": "rules.evaluated.v1",
                "payload": sensing_payload,
            })

        except Exception as e:
            logger.warning(f"背景規則監測失敗: {e}")


def _evaluate_rules_at_time(bundle, as_of: datetime):
    """使用指定時間做規則評估（模擬器專用）"""
    from src.models import SensingResult, RuleHit, EvidenceRef, TrafficLevel
    from src.rules import get_saturation, get_roaming_ratio, get_growth_rate
    
    rule_hits = []
    multilingual_required = False
    
    # SOP-1：交通擁塞級別（全 15 路段）
    _CITY_RESPONSE_SEGMENTS = {"RD_TPE_001", "RD_TPE_002"}
    
    for segment in bundle.road_network:
        sat = get_saturation(bundle, segment.segment_id, as_of)
        if sat is None:
            continue
        if sat >= 0.85:
            hit = RuleHit(
                clause_id="SOP-1",
                segment_id=segment.segment_id,
                evidence=EvidenceRef(
                    field="saturation_score",
                    value=sat,
                    threshold=0.95 if sat >= 0.95 else 0.85,
                ),
                is_primary=False,
                city_response=segment.segment_id in _CITY_RESPONSE_SEGMENTS,
            )
            rule_hits.append(hit)
    
    # SOP-3：捷運與接駁分流（BS_MRT_BL17）
    from src.rules import _as_of_crowd
    bl17_sample = _as_of_crowd(bundle, "BS_MRT_BL17", as_of)
    if bl17_sample is not None:
        if bl17_sample.growth_rate > 0.30 or bl17_sample.user_count > 25000:
            rule_hits.append(RuleHit(
                clause_id="SOP-3",
                station_id="BS_MRT_BL17",
                evidence=EvidenceRef(
                    field="growth_rate" if bl17_sample.growth_rate > 0.30 else "user_count",
                    value=bl17_sample.growth_rate if bl17_sample.growth_rate > 0.30 else bl17_sample.user_count,
                    threshold=0.30 if bl17_sample.growth_rate > 0.30 else 25000,
                ),
            ))
    
    # SOP-6：多語通報（任一站點 roaming_user_pct >= 0.30）
    all_station_ids = {c.station_id for c in bundle.crowd}
    for station_id in all_station_ids:
        ratio = get_roaming_ratio(bundle, station_id, as_of)
        if ratio is not None and ratio >= 0.30:
            multilingual_required = True
            rule_hits.append(RuleHit(
                clause_id="SOP-6",
                station_id=station_id,
                evidence=EvidenceRef(
                    field="roaming_user_pct",
                    value=ratio,
                    threshold=0.30,
                ),
            ))
    
    # 計算等級
    max_level: TrafficLevel = "normal"
    for hit in rule_hits:
        if hit.clause_id == "SOP-1":
            val = hit.evidence.value
            if isinstance(val, (int, float)):
                if val >= 0.95:
                    max_level = "A"
                elif val >= 0.85 and max_level != "A":
                    max_level = "B"
    
    return SensingResult(
        traffic_level=max_level,
        rule_hits=rule_hits,
        as_of=as_of,
        multilingual_required=multilingual_required,
    )

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


@app.post("/api/reset")
async def reset_state():
    """重設後端狀態（清空 active_incidents），供開發測試用。"""
    orchestrator.reset()
    return {"status": "ok", "message": "後端狀態已重設"}


# ========== 時間軸模擬器 API ==========

def _get_data_time_range():
    """取得資料的時間範圍"""
    bundle = orchestrator.GATEWAY.load_data()
    traffic_times = [t.timestamp for t in bundle.traffic]
    crowd_times = [c.timestamp for c in bundle.crowd]
    all_times = traffic_times + crowd_times
    if not all_times:
        return None, None
    return min(all_times), max(all_times)


def get_simulation_time():
    """取得當前模擬時間（供其他模組使用）"""
    if _simulation_state["enabled"] and _simulation_state["current_time"]:
        return _simulation_state["current_time"]
    return None


@app.get("/api/simulation")
async def get_simulation_state():
    """取得模擬器狀態"""
    start_time, end_time = _get_data_time_range()
    
    return {
        "status": "ok",
        "simulation": {
            "enabled": _simulation_state["enabled"],
            "playing": _simulation_state["playing"],
            "current_time": _simulation_state["current_time"].isoformat() if _simulation_state["current_time"] else None,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "speed": _simulation_state["speed"],
        }
    }


@app.post("/api/simulation/start")
async def start_simulation(body: dict = None):
    """啟動模擬器"""
    body = body or {}
    start_time, end_time = _get_data_time_range()
    
    if not start_time or not end_time:
        return {"status": "error", "message": "無法取得資料時間範圍"}
    
    _simulation_state["enabled"] = True
    _simulation_state["start_time"] = start_time
    _simulation_state["end_time"] = end_time
    _simulation_state["current_time"] = start_time
    _simulation_state["speed"] = body.get("speed", 60)  # 預設 1 秒跑 1 分鐘
    _simulation_state["playing"] = False
    _simulation_state["last_level"] = None
    
    # 重設後端狀態
    orchestrator.reset()
    global _last_traffic_level
    _last_traffic_level = None
    
    # 推播初始狀態
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {
            "action": "started",
            "current_time": start_time.isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }
    })
    
    return {"status": "ok", "message": "模擬器已啟動", "current_time": start_time.isoformat()}


@app.post("/api/simulation/play")
async def play_simulation():
    """開始播放"""
    if not _simulation_state["enabled"]:
        return {"status": "error", "message": "模擬器尚未啟動"}
    
    _simulation_state["playing"] = True
    
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {"action": "playing"}
    })
    
    return {"status": "ok", "message": "開始播放"}


@app.post("/api/simulation/pause")
async def pause_simulation():
    """暫停播放"""
    _simulation_state["playing"] = False
    
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {"action": "paused"}
    })
    
    return {"status": "ok", "message": "已暫停"}


@app.post("/api/simulation/reset")
async def reset_simulation():
    """重置模擬器"""
    if _simulation_state["start_time"]:
        _simulation_state["current_time"] = _simulation_state["start_time"]
        _simulation_state["playing"] = False
        _simulation_state["last_level"] = None
        
        orchestrator.reset()
        global _last_traffic_level
        _last_traffic_level = None
        
        await ws_manager.broadcast({
            "message_type": "simulation.state.v1",
            "payload": {
                "action": "reset",
                "current_time": _simulation_state["start_time"].isoformat()
            }
        })
    
    return {"status": "ok", "message": "已重置"}


@app.post("/api/simulation/stop")
async def stop_simulation():
    """停止模擬器"""
    _simulation_state["enabled"] = False
    _simulation_state["playing"] = False
    _simulation_state["current_time"] = None
    
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {"action": "stopped"}
    })
    
    return {"status": "ok", "message": "模擬器已停止"}


@app.post("/api/simulation/seek")
async def seek_simulation(body: dict):
    """跳到指定時間"""
    if not _simulation_state["enabled"]:
        return {"status": "error", "message": "模擬器尚未啟動"}
    
    time_str = body.get("time")
    if not time_str:
        return {"status": "error", "message": "time 為必填"}
    
    try:
        # 解析時間（支援 HH:MM 格式）
        if len(time_str) == 5 and ":" in time_str:
            # HH:MM 格式，補上日期
            base_date = _simulation_state["start_time"].date()
            hour, minute = map(int, time_str.split(":"))
            new_time = datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=_TZ_TAIPEI)
        else:
            new_time = datetime.fromisoformat(time_str)
            if new_time.tzinfo is None:
                new_time = new_time.replace(tzinfo=_TZ_TAIPEI)
        
        _simulation_state["current_time"] = new_time
        
        await ws_manager.broadcast({
            "message_type": "simulation.state.v1",
            "payload": {
                "action": "seeked",
                "current_time": new_time.isoformat()
            }
        })
        
        return {"status": "ok", "current_time": new_time.isoformat()}
    except Exception as e:
        return {"status": "error", "message": f"時間格式錯誤: {e}"}


# 模擬事件生成器配置
_SIM_EVENT_COUNTER = 0

_EVENT_TYPES = [
    {
        "type": "Traffic_Accident",
        "severities": ["Critical", "High", "Medium"],
        "statuses": ["Closed", "Restricted"],
        "descriptions": [
            "多車追撞事故，現場封閉處理中",
            "機車與行人擦撞，救護車到場處理",
            "公車與小客車碰撞，佔用車道",
            "計程車拋錨阻塞車道",
        ],
    },
    {
        "type": "Road_Collapse_Accident",
        "severities": ["Critical", "High"],
        "statuses": ["Closed"],
        "descriptions": [
            "路面塌陷，全線封閉搶修中",
            "地下管線破裂導致路面下陷",
            "大型坑洞出現，車輛無法通行",
        ],
    },
    {
        "type": "Crowd_Surge_Injury",
        "severities": ["High", "Medium"],
        "statuses": ["Restricted", "Caution"],
        "descriptions": [
            "大量人潮聚集造成推擠，有民眾受傷",
            "活動散場人流過大，需進行分流管制",
            "跨年人群擁擠，啟動疏散機制",
        ],
    },
    {
        "type": "Power_Failure",
        "severities": ["Medium", "High"],
        "statuses": ["Caution", "Restricted"],
        "descriptions": [
            "區域停電導致號誌失效，需人工指揮",
            "交通號誌故障閃爍，車流混亂",
            "路燈全滅，能見度不佳",
        ],
    },
    {
        "type": "Vehicle_Fire",
        "severities": ["Critical", "High"],
        "statuses": ["Closed", "Restricted"],
        "descriptions": [
            "車輛自燃，消防隊到場灌救中",
            "貨車起火，現場濃煙瀰漫",
            "機車電池爆炸起火",
        ],
    },
    {
        "type": "Water_Main_Break",
        "severities": ["Medium", "High"],
        "statuses": ["Restricted", "Caution"],
        "descriptions": [
            "自來水管爆裂，路面積水",
            "消防栓破裂，大量湧水影響通行",
        ],
    },
    {
        "type": "Debris_On_Road",
        "severities": ["Medium", "Low"],
        "statuses": ["Caution"],
        "descriptions": [
            "貨車掉落物散落路面，清理中",
            "工地建材掉落阻塞車道",
            "路樹倒塌佔用部分車道",
        ],
    },
]


@app.post("/api/incidents/generate")
async def generate_incident():
    """模擬事件生成器：隨機產生一筆新事件並執行決策流程。"""
    import random
    from datetime import datetime, timezone, timedelta

    global _SIM_EVENT_COUNTER
    _SIM_EVENT_COUNTER += 1

    tz = timezone(timedelta(hours=8))
    
    # 載入路網資料取得路段資訊
    bundle = orchestrator.GATEWAY.load_data()
    road_segments = [r for r in bundle.road_network if r.segment_id.startswith("RD_")]
    
    if not road_segments:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "INTERNAL_ERROR", "message": "無可用路段資料"}],
        })

    # 使用交通資料時間範圍內的隨機時間（而非系統當前時間）
    # 這樣 as-of 查詢才會拿到合理的飽和度資料
    traffic_timestamps = [t.timestamp for t in bundle.traffic]
    if traffic_timestamps:
        min_ts = min(traffic_timestamps)
        max_ts = max(traffic_timestamps)
        # 在資料範圍內隨機選一個時間點
        delta_seconds = int((max_ts - min_ts).total_seconds())
        random_offset = random.randint(0, max(1, delta_seconds))
        event_time = min_ts + timedelta(seconds=random_offset)
    else:
        event_time = datetime.now(tz=tz)

    # 隨機選擇事件類型
    event_config = random.choice(_EVENT_TYPES)
    
    # 隨機選擇路段
    road = random.choice(road_segments)
    
    # 隨機選擇嚴重度和狀態
    severity = random.choice(event_config["severities"])
    status = random.choice(event_config["statuses"])
    description_template = random.choice(event_config["descriptions"])
    
    # 組成事件 ID
    event_id = f"TPE_2026_SIM_{_SIM_EVENT_COUNTER:03d}"
    
    # 組成位置描述
    location = f"{road.name}"
    if road.intersections:
        intersection = random.choice(road.intersections)
        location = f"{road.name}與{intersection}路口"
    
    # 組成完整描述
    description = f"{event_time.strftime('%Y-%m-%d %H:%M')} {location} {description_template}"
    
    # 建立 Incident 物件
    from src.models import Incident, IncidentSeverity
    
    severity_enum = IncidentSeverity(severity)
    
    incident = Incident(
        event_id=event_id,
        type=event_config["type"],
        location=location,
        affected_segment=road.segment_id,
        affected_road=road.segment_id,  # 對於模擬事件，affected_road = affected_segment
        status=status,
        severity=severity_enum,
        description=description,
        timestamp=event_time,
    )

    # 廣播決策週期開始
    await ws_manager.broadcast({
        "message_type": "decision.cycle_start.v1",
        "payload": {"triggered_by": [event_id]},
    })

    # 執行決策流程
    decision_result = await orchestrator.handle_incident(incident, ws_broadcaster=ws_manager.broadcast)
    payload_json = decision_result.model_dump(mode="json")

    # 廣播警報（若等級為 A 或 B）
    if decision_result.level in ("A", "B"):
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": decision_result.level,
                "description": incident.description,
                "ete_minutes": decision_result.ete.minutes if decision_result.ete else None,
            },
        })

    # 廣播決策完成
    await ws_manager.broadcast({
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })

    # 廣播 Dashboard 更新
    await ws_manager.broadcast({
        "message_type": "dashboard.updated.v1",
        "payload": {"event_id": event_id, "level": decision_result.level},
    })

    return JSONResponse(content={
        "status": "ok",
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })


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



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
