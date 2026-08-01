"""[2026-08-02] 「情況變了要主動說」的回歸測試。

使用者的要求原文：「我的 report 隨著時間更改，我追問 chatbot 情況他應該要
可以知道情況改變了給我新的東西。」

在此之前模型手上有的是：最新的事實區塊 + 對話歷史裡的舊回答原文，兩者互相
矛盾，而**沒有任何一句話告訴它哪個是現在**。
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.agent.whatif_agent import build_change_block, snapshot_of, _build_prompt
from src.models import (
    DecisionResult,
    EteEstimate,
    Incident,
    IncidentSeverity,
    RouteCandidate,
    RoutePlan,
)
from src.orchestrator import IncidentRecord
from src.session.models import W1Context

_TZ = timezone(timedelta(hours=8))


def _candidate(seg_id, name, sat):
    return RouteCandidate(
        segment_id=seg_id, name=name, eligible=True, reason_code=None,
        saturation_score=sat, capacity_vph=2500, snapshot_at=None,
    )


def _record(primary, secondary, *, saturated=False, replans=0, report="報告書 v1"):
    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="光復南路/忠孝東路口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="路面塌陷",
        timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=_TZ),
    )
    routes = RoutePlan(
        primary=primary, secondary=secondary, excluded=[], findings=[], candidates=[],
        all_alternatives_saturated=saturated,
    )
    decision = DecisionResult(
        trace_id="TR-1", triggered_by=["§2"], level="A", incident=incident,
        routes=routes,
        ete=EteEstimate(minutes=90, recovery_at="2026-05-20 23:40",
                        formula="f", base_clearance=60, average_saturation=1.0),
        control_center_report=report, notifications=None, degraded=[],
        duration_ms=1, is_simulated=False,
    )
    return IncidentRecord(
        trace_id="TR-1", incident=incident, decision_result=decision,
        route_replan_count=replans,
    )


def test_no_change_produces_no_block():
    """路況沒動就不要每輪都宣告一次——那會讓真正重要的那次被當成雜訊。"""
    rec = _record(_candidate("RD_TPE_004", "市民大道四段", 0.78),
                  _candidate("RD_TPE_005", "仁愛路四段", 0.65))
    assert build_change_block(rec, snapshot_of(rec)) is None


def test_route_change_is_reported():
    before = snapshot_of(_record(_candidate("RD_TPE_004", "市民大道四段", 0.78),
                                 _candidate("RD_TPE_005", "仁愛路四段", 0.65)))
    after = _record(_candidate("RD_TPE_005", "仁愛路四段", 0.72), None, replans=1)

    block = build_change_block(after, before)
    assert block is not None
    assert "市民大道四段" in block and "仁愛路四段" in block
    assert "重新規劃" in block
    assert "必須在回覆開頭用一句話主動說明情況已改變" in block


def test_becoming_no_alternative_is_reported_loudly():
    """從「有路可走」變成「無路可替補」是最需要主動講的一種改變。"""
    before = snapshot_of(_record(_candidate("RD_TPE_005", "仁愛路四段", 0.72), None))
    after = _record(_candidate("RD_TPE_004", "市民大道四段", 0.95),
                    _candidate("RD_TPE_005", "仁愛路四段", 0.85),
                    saturated=True, replans=2)

    block = build_change_block(after, before)
    assert block is not None
    assert "無路段可以替補" in block


def test_report_revision_is_reported():
    before = snapshot_of(_record(_candidate("RD_TPE_004", "市民大道四段", 0.78),
                                 None, report="報告書 v1"))
    after = _record(_candidate("RD_TPE_004", "市民大道四段", 0.78), None,
                    report="報告書 v2，內容更長一些")
    block = build_change_block(after, before)
    assert block is not None and "建議書已更新" in block


def test_different_event_is_not_diffed():
    """換一起事件在看就不是「同一件事的變化」，diff 沒有意義。"""
    before = snapshot_of(_record(_candidate("RD_TPE_004", "市民大道四段", 0.78), None))
    before = dict(before, trace_id="TR-OTHER")
    after = _record(_candidate("RD_TPE_005", "仁愛路四段", 0.72), None)
    assert build_change_block(after, before) is None


def test_snapshot_is_frozen_not_a_live_reference():
    """快照必須凍結在當時，否則決策物件被替換後 diff 永遠是空的。"""
    rec = _record(_candidate("RD_TPE_004", "市民大道四段", 0.78), None)
    snap = snapshot_of(rec)
    rec.decision_result.routes.primary = _candidate("RD_TPE_005", "仁愛路四段", 0.72)
    assert snap["primary"]["segment_id"] == "RD_TPE_004"
    assert build_change_block(rec, snap) is not None


# --- prompt 組裝 ---


def _ctx(**kw):
    base = dict(session_id="s", new_message="現在情況如何", history=[],
                accumulated_assumptions={})
    base.update(kw)
    return W1Context(**base)


def test_change_block_precedes_history_in_prompt():
    """順序很重要：讀到歷史那些舊數字之前，模型要先知道它們是變化前講的。"""
    from src.session.models import Turn

    turn = Turn(user_message="q", ai_response="主線市民大道四段",
                timestamp=datetime(2026, 5, 20, 22, 15, tzinfo=_TZ))
    prompt = _build_prompt(_ctx(history=[turn]), "事實", "=== 自你上一次回答以來的變化 ===\n- 主線換了")

    assert prompt.index("自你上一次回答以來的變化") < prompt.index("對話歷史")
    assert "以上回答是在情況改變**之前**給的" in prompt


def test_dropped_assumptions_are_declared_in_prompt():
    """歷史還在 prompt 裡，不明說作廢的話模型會繼續沿用那個前提。"""
    prompt = _build_prompt(
        _ctx(assumption_scope="replace",
             dropped_assumptions={"RD_TPE_003.status": "Closed"}),
        "事實",
        None,
    )
    assert "假設情境已重置" in prompt
    assert "（已失效）RD_TPE_003.status = Closed" in prompt
    assert "不得帶入本次的 simulate_scenario" in prompt


def test_no_change_block_means_no_stale_history_warning():
    from src.session.models import Turn

    turn = Turn(user_message="q", ai_response="a",
                timestamp=datetime(2026, 5, 20, 22, 15, tzinfo=_TZ))
    prompt = _build_prompt(_ctx(history=[turn]), "事實", None)
    assert "情況改變" not in prompt
