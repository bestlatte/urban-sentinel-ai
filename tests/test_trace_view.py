"""決策軌跡對外暴露的回歸測試。

背景：使用者反映「chatbot 的回答沒有顯示決策軌跡」。原因是軌跡從來沒有離開過
後端記憶體——`decision_trace` 只被 M4B 生成層在行程內讀取，`W1Response` 沒有
對應欄位，也沒有任何端點暴露它。前端 F7「決策依據」分頁看起來像在顯示軌跡，
其實是自己從 WebSocket 的 task_update 事件拼的活動紀錄（「發生了什麼」，
不是「依據什麼判斷」）。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from fastapi.testclient import TestClient

from main import app
from src.decision_trace import (
    ExcludedItem,
    Finding,
    get_trace_view,
    open_trace,
    record_step,
    reset_traces,
)


@pytest.fixture(autouse=True)
def clean_traces():
    reset_traces()
    yield
    reset_traces()


def _seed_trace(trace_id: str = "TR-VIEW-01") -> str:
    open_trace(trace_id, ["§2"])
    record_step(
        trace_id,
        "A2",
        "PLAN",
        {"event_id": "E1"},
        {"planned_by": "static_dispatch", "tools": ["RAG_SEARCH", "ROUTE_SELECT"]},
    )
    record_step(
        trace_id,
        "R4",
        "TOOL_CALL",
        {"event_id": "E1"},
        {"primary": "RD_TPE_004", "secondary": "RD_TPE_005", "excluded_count": 2},
        tool="ROUTE_SELECT",
        sop_ref="§2",
        excluded=[
            ExcludedItem("RD_TPE_008", "CAPACITY_INSUFFICIENT", "延吉街：容量 600 vph"),
        ],
        findings=[Finding("SATURATED_BUT_RETAINED", ["RD_TPE_004"], {"saturation_score": 0.98})],
        subject_segment_ids=["RD_TPE_004", "RD_TPE_005"],
        duration_ms=7,
    )
    return trace_id


def test_get_trace_view_returns_none_for_unknown_id():
    assert get_trace_view("TR-DOES-NOT-EXIST") is None


def test_trace_view_shape():
    trace_id = _seed_trace()
    view = get_trace_view(trace_id)

    assert view["trace_id"] == trace_id
    assert view["triggered_by"] == ["§2"]
    assert len(view["steps"]) == 2
    assert [s["sequence_no"] for s in view["steps"]] == [1, 2]


def test_trace_view_translates_actor_codes():
    """R4 這種代碼要換成人話，指揮官不會背 ActorCode 表。"""
    view = get_trace_view(_seed_trace())
    route_step = view["steps"][1]

    assert route_step["agent"] == "R4"
    assert route_step["agent_label"] == "路線選擇"
    assert route_step["action_label"] == "呼叫工具"


def test_trace_view_carries_excluded_and_findings():
    """排除理由是回溯追問最該回答的東西——「延吉街為什麼不能走」。"""
    view = get_trace_view(_seed_trace())
    route_step = view["steps"][1]

    assert route_step["excluded"] == [
        {
            "segment_id": "RD_TPE_008",
            "reason_code": "CAPACITY_INSUFFICIENT",
            "detail": "延吉街：容量 600 vph",
        }
    ]
    assert route_step["findings"][0]["finding_code"] == "SATURATED_BUT_RETAINED"
    assert route_step["findings"][0]["evidence"] == {"saturation_score": 0.98}


def test_trace_view_is_json_serialisable():
    """要能直接丟給 JSONResponse——TraceStep 內含 datetime 與巢狀 dataclass。"""
    import json

    json.dumps(get_trace_view(_seed_trace()), ensure_ascii=False)


def test_trace_view_omits_input_payload():
    """`input` 常含整包 classification 與 batch，對畫面無價值只會灌大 payload。"""
    view = get_trace_view(_seed_trace())
    for step in view["steps"]:
        assert "input" not in step


# ---------------------------------------------------------------------------
# 端點與對話整合
# ---------------------------------------------------------------------------


def test_trace_endpoint_returns_view():
    trace_id = _seed_trace()
    with TestClient(app) as client:
        d = client.get(f"/api/trace/{trace_id}").json()

    assert d["status"] == "ok"
    assert d["message_type"] == "trace.view.v1"
    assert len(d["payload"]["steps"]) == 2


def test_trace_endpoint_unknown_id_is_data_not_found_not_500():
    """軌跡存在記憶體，伺服器重啟後舊 ID 會查不到——那是資料問題不是伺服器錯誤。"""
    with TestClient(app) as client:
        d = client.get("/api/trace/TR-NOPE").json()

    assert d["status"] == "error"
    assert d["errors"][0]["code"] == "DATA_NOT_FOUND"


def test_chat_reply_carries_trace_steps():
    """帶 current_trace_id 的對話回覆必須含軌跡——這是使用者回報的缺口本身。"""
    trace_id = _seed_trace()
    with TestClient(app) as client:
        d = client.post("/api/what-if", json={
            "session_id": "s-trace",
            "content": "延吉街為什麼不能走",
            "current_trace_id": trace_id,
            "correlation_id": "c",
        }).json()

    payload = d["payload"]
    assert payload["trace_id"] == trace_id
    assert payload["trace_steps"], "對話回覆沒有帶決策軌跡"
    assert any(s["agent"] == "R4" for s in payload["trace_steps"])


def test_chat_reply_without_trace_id_has_empty_trace():
    """沒有進行中的週期時不得炸，只是沒有軌跡可附。"""
    with TestClient(app) as client:
        d = client.post("/api/what-if", json={
            "session_id": "s-no-trace",
            "content": "目前狀況如何",
            "correlation_id": "c",
        }).json()

    payload = d["payload"]
    assert payload["trace_steps"] == []
    assert payload["trace_id"] is None
