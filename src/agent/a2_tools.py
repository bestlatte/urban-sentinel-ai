"""A2 Orchestrator 的 Strands @tool 包裝：把 GATEWAY 方法包成工具介面。

這三個工具供 A2 LLM 規劃器（SPEC-O2 §3 事件注入流程）使用：
LLM 決定呼叫哪些工具、什麼順序，但實際計算全部由 Python 決定性模組執行。
純包裝，計算邏輯不變。
"""

from __future__ import annotations

from strands import tool


@tool
def evaluate_rules_tool(event_id: str = "") -> dict:
    """評估全路網規則（P1-P5），回傳交通等級與命中的 SOP 條款。

    何時使用：需要知道目前全市交通狀態、哪些 SOP 被觸發。
    """
    from src import orchestrator

    bundle = orchestrator.GATEWAY.load_data()

    # 如果有指定 event_id，找對應 incident
    incident = None
    if event_id:
        matched = [i for i in bundle.incidents if i.event_id == event_id]
        if matched:
            incident = matched[0]

    sensing = orchestrator.GATEWAY.evaluate_rules(bundle, incident)
    return {
        "traffic_level": sensing.traffic_level,
        "rule_hits": [
            {"clause_id": h.clause_id, "segment_id": h.segment_id, "station_id": h.station_id}
            for h in sensing.rule_hits
        ],
        "multilingual_required": sensing.multilingual_required,
    }


@tool
def plan_routes_tool(event_id: str) -> dict:
    """為指定事件規劃替代路線（R1-R5），回傳主次路線與排除理由。

    何時使用：事件需要路網重規劃時（如 SOP-2 車禍路障）。

    Args:
        event_id: 事件 ID（如 TPE_2026_ACC_001）
    """
    from src import orchestrator
    from src.models import RouteRequest

    bundle = orchestrator.GATEWAY.load_data()
    matched = [i for i in bundle.incidents if i.event_id == event_id]
    if not matched:
        return {"error": f"event_id '{event_id}' 不存在"}

    incident = matched[0]
    request = RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp)
    plan = orchestrator.GATEWAY.plan_routes(request)

    return {
        "primary": {"segment_id": plan.primary.segment_id, "name": plan.primary.name} if plan.primary else None,
        "secondary": {"segment_id": plan.secondary.segment_id, "name": plan.secondary.name} if plan.secondary else None,
        "excluded": [
            {"segment_id": e.segment_id, "name": e.name, "reason_code": e.reason_code}
            for e in plan.excluded
        ],
        "no_feasible_route": plan.no_feasible_route,
    }


@tool
def calculate_ete_tool(event_id: str) -> dict:
    """為指定事件計算預計恢復時間（ETE）。

    何時使用：需要知道事件多久能恢復。

    Args:
        event_id: 事件 ID（如 TPE_2026_ACC_001）
    """
    from src import orchestrator

    bundle = orchestrator.GATEWAY.load_data()
    matched = [i for i in bundle.incidents if i.event_id == event_id]
    if not matched:
        return {"error": f"event_id '{event_id}' 不存在"}

    incident = matched[0]
    ete = orchestrator.GATEWAY.calculate_ete(incident, bundle)

    return {
        "minutes": ete.minutes,
        "recovery_at": ete.recovery_at,
        "formula": ete.formula,
        "base_clearance": ete.base_clearance,
        "average_saturation": ete.average_saturation,
    }
