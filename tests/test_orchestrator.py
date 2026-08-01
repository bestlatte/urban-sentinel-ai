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


# ---------------------------------------------------------------------------
# [2026-08-02 回歸] 隨時間推進的多次重規劃：候選全數飽和時要說「無路可替補」
# ---------------------------------------------------------------------------


def _seed_acc001_for_replan(as_of_initial: datetime) -> None:
    """把 ACC_001 塞進 active_incidents，模擬事故剛發生時的初次決策結果。"""
    from src.reporting import calculate_ete
    from src.routing import plan_route
    from src.models import RouteRequest
    from src.rules import evaluate_rules

    orchestrator.GATEWAY = orchestrator.build_gateway()
    bundle = orchestrator.GATEWAY.load_data()

    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="光復南路/忠孝東路口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="路面塌陷",
        timestamp=as_of_initial,
    )
    sensing = evaluate_rules(bundle, incident, as_of_initial)
    routes = plan_route(RouteRequest(incident=incident, bundle=bundle, as_of=as_of_initial))
    ete = calculate_ete(incident, bundle)

    get_global_state().active_incidents["TPE_2026_ACC_001"] = IncidentRecord(
        trace_id="TR-TEST-ACC001",
        incident=incident,
        bundle_snapshot=bundle,
        sensing_result=sensing,
        decision_result=DecisionResult(
            trace_id="TR-TEST-ACC001",
            triggered_by=["§2"],
            level="A",
            incident=incident,
            routes=routes,
            ete=ete,
            control_center_report="（初次建議書）",
            notifications=None,
            degraded=[],
            duration_ms=10,
            is_simulated=False,
        ),
    )


def test_second_replan_reports_no_alternative_when_all_candidates_saturated(monkeypatch):
    """時間推進到候選全數飽和時，重規劃必須回報「已無可替補路段」並更新報告書。

    實測時序（真實資料 data/city_traffic_flow.json，事故 RD_TPE_002 22:10）：

        22:10 主線 市民大道四段(0.78) / 次線 仁愛路四段(0.65)
        22:15 市民大道四段 0.85 飽和 → 第一次重規劃 → 主線改仁愛路四段(0.72)
        22:30 仁愛路四段 0.85 飽和 → **第二次重規劃 → 兩條都飽和，已無路可替補**

    修正前的行為：`RoutePlan.no_feasible_route` 只在 `primary is None` 時為 True，
    而 SOP-2 §2a 例外會指派飽和路線，所以它永遠是 False。整條鏈（orchestrator →
    WS payload → 前端）因此拿不到任何「沒有路可以替補」的訊號，畫面照常顯示
    「🔄 路線更新／已重新規劃替代路線」。
    """
    monkeypatch.setenv("USE_BEDROCK", "false")
    reset()
    _seed_acc001_for_replan(datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI))

    first = check_and_replan_routes(
        "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, 15, tzinfo=_TZ_TAIPEI)
    )
    assert first is not None and first.replanned
    assert first.route_changed is True
    assert first.no_alternative_available is False, "22:15 仁愛路四段還沒飽和，仍有可替補路段"

    second = check_and_replan_routes(
        "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI)
    )
    assert second is not None and second.replanned
    assert second.no_alternative_available is True, "候選全數飽和 → 必須回報無可替補路段"

    routes = second.new_decision_result.routes
    assert routes.all_alternatives_saturated is True
    assert routes.primary is not None, "SOP-2 §2a 例外：仍要指派最不糟的那條"
    assert "SATURATED_BUT_RETAINED" in [f.finding_code for f in routes.findings]

    # 報告書必須跟著改寫，而不是沿用暢通時的措辭
    report = second.new_decision_result.control_center_report
    assert report and report != "（初次建議書）"
    assert "無可替補" in report or "無可行替代路線" in report


def test_replan_that_keeps_the_same_route_is_not_reported_as_a_route_change(monkeypatch):
    """重規劃後主/次線一模一樣時，`route_changed` 必須是 False。

    修正前 `check_and_replan_routes()` 一律回 `replanned=True` 也不做新舊比對，
    前端據此畫出「✗ 原路線: 市民大道四段 ／ ✓ 新路線: 市民大道四段」——
    同一條路同時是被淘汰的與新採用的。實測 22:45 就是這個情形。
    """
    monkeypatch.setenv("USE_BEDROCK", "false")
    reset()
    _seed_acc001_for_replan(datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI))

    for hh, mm in [(22, 15), (22, 30)]:
        check_and_replan_routes(
            "TPE_2026_ACC_001", datetime(2026, 5, 20, hh, mm, tzinfo=_TZ_TAIPEI)
        )

    third = check_and_replan_routes(
        "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, 45, tzinfo=_TZ_TAIPEI)
    )
    assert third is not None and third.replanned
    assert third.old_primary == third.new_primary
    assert third.route_changed is False, "新舊主線相同就不能宣稱換過路線"
    assert third.no_alternative_available is True


def test_monitoring_every_minute_produces_two_updates_over_the_timeline(monkeypatch):
    """整條時間軸應該出現兩次路線更新，第二次是「無路可替補」。

    [2026-08-02 回歸] 這是使用者實際回報的症狀：整場模擬只跳一次警示，
    而且新舊路線相同。原因不在 routing，而在 main.py 的監測**只在路段等級
    變化的那一分鐘**才跑（邊緣觸發），漏掉兩種情況：

      1. 建議書生成期間（LLM ~20 秒 = 20 模擬分鐘）事件的 decision_result
         還是 None，那一刻的飽和事件被 `continue` 丟掉；等級已記成 B，
         之後不會再「變化」，那次重規劃永久消失 → 22:15 的換路沒發生。
      2. 22:45 兩條路都更塞了（0.95→0.98、0.85→0.92）但等級都沒跨門檻
         （A 仍是 A、B 仍是 B）→ 完全不檢查。

    於是整場只剩 22:30 觸發一次，而那時路線還停在 22:10 的規劃結果、
    主次線同時飽和、重規劃又選回同一條 → 「原路線=新路線」。

    改成每分鐘檢查（狀態觸發）後，本測試鎖住正確的時序。
    """
    monkeypatch.setenv("USE_BEDROCK", "false")
    reset()
    _seed_acc001_for_replan(datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI))

    updates = []
    t = datetime(2026, 5, 20, 22, 11, tzinfo=_TZ_TAIPEI)
    end = datetime(2026, 5, 20, 23, 0, tzinfo=_TZ_TAIPEI)
    while t <= end:
        r = check_and_replan_routes("TPE_2026_ACC_001", t)
        if r is not None and r.replanned:
            updates.append((t.strftime("%H:%M"), r))
        t += timedelta(minutes=1)

    assert len(updates) >= 2, f"整條時間軸至少要有兩次路線更新，實際 {len(updates)} 次"

    first_time, first = updates[0]
    assert first_time == "22:15", "市民大道四段 22:15 飽和，第一次換路就該在這一分鐘"
    assert first.route_changed is True
    assert first.new_primary == "RD_TPE_005", "第一次應改走仁愛路四段"
    assert first.no_alternative_available is False

    second_time, second = updates[1]
    assert second_time == "22:30", "仁愛路四段 22:30 也飽和，第二次更新在這一分鐘"
    assert second.no_alternative_available is True, "第二次必須回報『目前無路段可以替補』"


def test_unchanged_conditions_do_not_retrigger_replan(monkeypatch):
    """路況沒變就不重複重規劃——否則每個模擬分鐘都會重跑一次 LLM 建議書。

    監測改成每分鐘都跑之後，路線一旦飽和就會分分鐘判定 needs_replan。
    去重靠 `IncidentRecord.last_route_state_signature`，比對點在算完路線之後、
    生成建議書之前，所以狀況沒變時不會付出 LLM 的成本。
    """
    monkeypatch.setenv("USE_BEDROCK", "false")
    reset()
    _seed_acc001_for_replan(datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI))

    # 22:30~22:44 路況完全相同（下一筆快照是 22:45）
    first = check_and_replan_routes(
        "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI)
    )
    assert first is not None and first.replanned

    for minute in range(31, 45):
        again = check_and_replan_routes(
            "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, minute, tzinfo=_TZ_TAIPEI)
        )
        assert again is not None
        assert again.replanned is False, f"22:{minute} 路況未變，不該重複重規劃"

    # 22:45 飽和度真的變了（0.95→0.98、0.85→0.92）→ 必須重新通報
    worsened = check_and_replan_routes(
        "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, 45, tzinfo=_TZ_TAIPEI)
    )
    assert worsened is not None and worsened.replanned is True, "路況惡化必須重推更新過的建議書"
    assert worsened.no_alternative_available is True


def test_affected_route_type_derived_from_validity_not_level_change():
    """`_affected_route_type()` 要能在任何時刻判斷，不依賴「剛剛變飽和」的路段清單。"""
    from main import _affected_route_type

    routes = RoutePlan(
        primary=RouteCandidate(
            segment_id="RD_TPE_004", name="市民大道四段", eligible=True,
            reason_code=None, saturation_score=0.95, capacity_vph=2500, snapshot_at=None,
        ),
        secondary=RouteCandidate(
            segment_id="RD_TPE_005", name="仁愛路四段", eligible=True,
            reason_code=None, saturation_score=0.85, capacity_vph=4000, snapshot_at=None,
        ),
        excluded=[], findings=[], candidates=[],
    )

    assert _affected_route_type(routes, {"RD_TPE_004": "SATURATED_0.95"}) == "primary"
    assert _affected_route_type(routes, {"RD_TPE_005": "SATURATED_0.85"}) == "secondary"
    assert _affected_route_type(
        routes, {"RD_TPE_004": "SATURATED_0.95", "RD_TPE_005": "SATURATED_0.85"}
    ) == "both"
    assert _affected_route_type(routes, {}) is None
    assert _affected_route_type(None, {"RD_TPE_004": "x"}) is None


def test_replan_keeps_projected_risks(monkeypatch):
    """重規劃重建 DecisionResult 時不得把風險推演弄丟。"""
    monkeypatch.setenv("USE_BEDROCK", "false")
    reset()
    _seed_acc001_for_replan(datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI))

    result = check_and_replan_routes(
        "TPE_2026_ACC_001", datetime(2026, 5, 20, 22, 15, tzinfo=_TZ_TAIPEI)
    )
    assert result is not None and result.new_decision_result is not None
    assert result.new_decision_result.projected_risks is not None
