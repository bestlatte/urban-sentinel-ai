"""Orchestrator 整合測試：三分支路由 + 黃金值回歸 + message_type 正確性。"""

import os
os.environ.setdefault("USE_BEDROCK", "false")

from fastapi.testclient import TestClient
from main import app


def test_post_what_if_routes_to_whatif_for_hypothetical_question():
    """SPEC-O3 §4：含前瞻詞 → whatif.evaluated.v1。"""
    with TestClient(app) as client:
        r = client.post("/api/what-if", json={"session_id": "s1", "content": "如果BL17到40000", "correlation_id": "c1"})
        d = r.json()
        assert d["status"] == "ok"
        assert d["message_type"] == "whatif.evaluated.v1"


def test_post_what_if_routes_general_question_to_agent():
    """[2026-08-01 行為變更] 非前瞻、無 trace_id 的一般問題 → 交給 W1 Agent。

    原本這裡斷言的是「→ trace.answered.v1 + 一句固定引導文字」，那正是實際
    回報的「chatbot 問到不會的就死掉」：只要問題不含「如果」又沒有進行中的
    決策週期，不管問什麼都回同一句話。

    現在的規則是「非回溯問題一律進 Agent」——模型手上有 query_sop 與
    simulate_scenario，該不該查 SOP 由它自己判斷，不再用關鍵字先替它決定。
    """
    with TestClient(app) as client:
        r = client.post("/api/what-if", json={"session_id": "s2", "content": "目前狀況如何", "correlation_id": "c2"})
        d = r.json()
        assert d["status"] == "ok"
        assert d["message_type"] == "whatif.evaluated.v1"


def test_what_if_payload_always_has_summary_field():
    """所有路由分支的 payload 都必須是 W1Response 形狀。

    回歸測試：回溯分支原本回 `{"trace_id", "answer_text"}`，而前端
    `chat-render.js::renderAIResponse()` 讀的是 `summary`——欄位名對不上，
    畫面上就是一個**完全空白的 AI 泡泡**。這是「chatbot 死了」的直接成因，
    不是模型答不出來。
    """
    with TestClient(app) as client:
        for content in ("目前狀況如何", "如果BL17到40000", "你好"):
            r = client.post(
                "/api/what-if",
                json={"session_id": "s3", "content": content, "correlation_id": "c3"},
            )
            payload = r.json()["payload"]
            assert "summary" in payload, f"{content!r} 的 payload 缺少 summary"
            assert payload["summary"], f"{content!r} 的 summary 是空的"
            assert "suggested_questions" in payload


def test_decision_completed_message_type_not_decision_result():
    """WS 推播用 decision.completed.v1，不是 decision.result.v1。"""
    with TestClient(app) as client:
        r = client.post("/api/incidents/evaluate", json={"event_id": "TPE_2026_ACC_001"})
        d = r.json()
        assert d["message_type"] == "decision.completed.v1"
        assert "decision.result.v1" != d["message_type"]


def test_acc001_golden_regression_full_pipeline():
    """ACC_001 全流程：主004/次005/排除006、008/ETE 90分/恢復23:40。"""
    with TestClient(app) as client:
        r = client.post("/api/incidents/evaluate", json={"event_id": "TPE_2026_ACC_001"})
        d = r.json()
        assert d["status"] == "ok"
        p = d["payload"]
        assert p["ete"]["minutes"] == 90
        assert p["ete"]["recovery_at"] == "2026-05-20 23:40"
        assert p["routes"]["primary"]["segment_id"] == "RD_TPE_004"
        assert p["routes"]["secondary"]["segment_id"] == "RD_TPE_005"
        excluded_ids = {e["segment_id"] for e in p["routes"]["excluded"]}
        assert "RD_TPE_006" in excluded_ids
        assert "RD_TPE_008" in excluded_ids


# ---------------------------------------------------------------------------
# 路線動態重規劃測試 (check_and_replan_routes / monitor_all_active_routes)
# ---------------------------------------------------------------------------

from datetime import datetime, timezone, timedelta
from src import orchestrator
from src.orchestrator import (
    check_and_replan_routes,
    monitor_all_active_routes,
    RouteMonitorResult,
    IncidentRecord,
    get_global_state,
    reset,
)
from src.models import Incident, IncidentSeverity, DecisionResult, RoutePlan, RouteCandidate

_TZ_TAIPEI = timezone(timedelta(hours=8))


def test_check_and_replan_routes_nonexistent_event():
    """不存在的 event_id 回傳 None。"""
    reset()
    result = check_and_replan_routes("NONEXISTENT", datetime.now(_TZ_TAIPEI))
    assert result is None


def test_check_and_replan_routes_no_decision_result():
    """event_id 存在但尚無 decision_result，回傳 None。"""
    reset()
    state = get_global_state()
    
    incident = Incident(
        event_id="TEST_001",
        type="Road_Collapse_Accident",
        location="測試路口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="測試事件",
        timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI),
    )
    state.active_incidents["TEST_001"] = IncidentRecord(
        trace_id="TR-TEST-001",
        incident=incident,
        decision_result=None,  # 尚無結果
    )
    
    result = check_and_replan_routes("TEST_001", datetime.now(_TZ_TAIPEI))
    assert result is None


def test_check_and_replan_routes_no_routes():
    """事件有 decision_result 但沒有 routes（如 SOP-5），回傳 None。"""
    reset()
    state = get_global_state()
    
    incident = Incident(
        event_id="TEST_002",
        type="Power_Failure",
        location="號誌故障路口",
        affected_segment="RD_TPE_007",
        status="Caution",
        severity=IncidentSeverity.MEDIUM,
        description="號誌故障",
        timestamp=datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI),
    )
    decision = DecisionResult(
        trace_id="TR-TEST-002",
        triggered_by=["§5"],
        level="B",
        incident=incident,
        routes=None,  # SOP-5 不需要路網規劃
        ete=None,
        control_center_report=None,
        notifications=None,
        degraded=[],
        duration_ms=100,
        is_simulated=False,
    )
    state.active_incidents["TEST_002"] = IncidentRecord(
        trace_id="TR-TEST-002",
        incident=incident,
        decision_result=decision,
    )
    
    result = check_and_replan_routes("TEST_002", datetime.now(_TZ_TAIPEI))
    assert result is None


def test_monitor_all_active_routes_empty_state():
    """沒有活躍事件時，回傳空 list。"""
    reset()
    results = monitor_all_active_routes(datetime.now(_TZ_TAIPEI))
    assert results == []
