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


def test_post_what_if_routes_to_trace_answer_for_retrospective_question():
    """回溯追問（無前瞻詞 + 無 trace_id）→ trace.answered.v1 + 固定引導文字。"""
    with TestClient(app) as client:
        r = client.post("/api/what-if", json={"session_id": "s2", "content": "目前狀況如何", "correlation_id": "c2"})
        d = r.json()
        assert d["status"] == "ok"
        assert d["message_type"] == "trace.answered.v1"
        assert "trace_id" in d["payload"]


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
