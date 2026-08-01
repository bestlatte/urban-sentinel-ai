"""二階效應推演的回歸測試。

這個模組回答的是建議書原本完全沒有回答的問題：「照這個方案做，接下來會怎樣」。
用 ACC_001 的真實資料測，因為這個模組的價值就在於**推出來的東西跟現實對得上**，
用捏造的 bundle 測不出這件事。
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import orchestrator
from src.models import Incident, IncidentSeverity, RouteRequest
from src.risk_projection import (
    PRIMARY_ROUTE_SHARE,
    TRANSFER_CAPTURE_RATE,
    build_risk_block,
    project_risks,
    projection_to_dict,
)


@pytest.fixture(scope="module")
def ctx():
    orchestrator.GATEWAY = orchestrator.build_gateway()
    gw = orchestrator.GATEWAY
    bundle = gw.load_data()
    incident = next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")
    sensing = gw.evaluate_rules(bundle, incident)
    route_plan = gw.plan_routes(
        RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp)
    )
    ete = gw.calculate_ete(incident, bundle)
    return {
        "bundle": bundle,
        "incident": incident,
        "sensing": sensing,
        "route_plan": route_plan,
        "ete": ete,
    }


def _project(ctx):
    return project_risks(
        ctx["incident"], ctx["route_plan"], ctx["sensing"], ctx["bundle"], ctx["ete"].minutes
    )


def test_primary_route_is_flagged_as_future_risk(ctx):
    """核心主張：系統推薦的主替代路線自己會飽和，這件事必須被算出來。

    這是整個模組存在的理由。ACC_001 建議改道市民大道四段（當下 0.78），
    而該路段在事故後 20 分鐘內就會達 A 級——建議書原本一個字都沒提，
    指揮官照著做，然後在 22:30 面對一個本來可以預先處置的新事件。
    """
    projection = _project(ctx)
    primary_id = ctx["route_plan"].primary.segment_id

    risky = [r for r in projection.risks if r.segment_id == primary_id]
    assert risky, "主替代路線的後續飽和風險沒有被推演出來"
    assert any(r.level == "A" for r in risky), "沒有推出主替代路線會達 A 級"


def test_projection_matches_observed_data_direction(ctx):
    """模型推出的時間點要跟資料集後續實際觀測對得上（同一個量級）。

    這不是精度測試——模型參數是對這一筆事件校準的，能吻合是預期的。這條測試
    守的是「有人改了參數或公式，導致推演跟現實脫節」而沒人發現。

    實際觀測：RD_TPE_004 在 22:15 達 0.85、22:30 達 0.95（事故 22:10）。
    容許 ±15 分鐘誤差——推演是給人「大約多久要動手」的判斷，不是時刻表。
    """
    projection = _project(ctx)
    primary_id = ctx["route_plan"].primary.segment_id

    by_level = {r.level: r for r in projection.risks if r.segment_id == primary_id}

    assert "B" in by_level, "沒推出 B 級風險"
    assert abs(by_level["B"].at_minutes - 5) <= 15, (
        f"B 級時間點 {by_level['B'].at_minutes} 分偏離觀測值（5 分）過多"
    )
    assert "A" in by_level
    assert abs(by_level["A"].at_minutes - 20) <= 15, (
        f"A 級時間點 {by_level['A'].at_minutes} 分偏離觀測值（20 分）過多"
    )


def test_baseline_uses_observed_saturation_not_derived(ctx):
    """基準飽和度必須用觀測值，不能用 vehicle_count/capacity 自己算。

    回歸測試：兩者是不同定義。實測 RD_TPE_004 的 2300/2500 = 0.92，
    但觀測 saturation_score 是 0.78。第一版用推導值當基準，推演一開始就
    平白跳了 0.14，整個時間軸往前偏。
    """
    projection = _project(ctx)
    primary_id = ctx["route_plan"].primary.segment_id
    risk = next(r for r in projection.risks if r.segment_id == primary_id)

    assert risk.baseline_saturation == pytest.approx(0.78, abs=0.01)
    derived = risk.evidence["baseline_vehicle_count"] / risk.evidence["capacity_vph"]
    assert abs(derived - risk.baseline_saturation) > 0.1, (
        "這筆資料的推導值與觀測值本來就不同；若相同則本測試失去意義"
    )


def test_primary_route_bears_majority_of_transfer(ctx):
    """車流依「系統指定哪條路線」分配，不是依剩餘容量。

    回歸測試：第一版按剩餘容量分配，算出主線只承接 7%——因為市民大道四段
    幾乎沒餘裕、仁愛路四段很空。但 CMS 上寫著「請改道市民大道四段」，車就往
    那裡去。按容量分配會讓「推薦路線會不會爆」這個問題永遠答不出來。
    """
    projection = _project(ctx)
    primary_id = ctx["route_plan"].primary.segment_id
    risk = next(r for r in projection.risks if r.segment_id == primary_id)

    assert risk.evidence["transferred_share"] == pytest.approx(PRIMARY_ROUTE_SHARE, abs=0.01)


def test_capture_rate_applied(ctx):
    """不是 100% 的車流都會落到指定替代路線上。"""
    projection = _project(ctx)
    primary_id = ctx["route_plan"].primary.segment_id
    risk = next(r for r in projection.risks if r.segment_id == primary_id)

    expected = projection.transferred_vehicles * TRANSFER_CAPTURE_RATE * PRIMARY_ROUTE_SHARE
    assert risk.evidence["transferred_vehicles"] == pytest.approx(expected, rel=0.02)


def test_every_risk_carries_a_mitigation(ctx):
    """每個風險都必須附對策——只講「會出問題」不講「怎麼辦」等於製造焦慮。"""
    projection = _project(ctx)
    assert projection.risks
    for r in projection.risks:
        assert r.mitigation, f"{r.segment_name} {r.level} 級風險沒有對策"
        assert r.clause_id, "對策必須標明依據哪條 SOP"


def test_assumptions_are_always_disclosed(ctx):
    """推演假設一律攤開——這是推估不是觀測，讀的人有權質疑它建立在什麼之上。"""
    projection = _project(ctx)
    assert len(projection.assumptions) >= 3
    joined = " ".join(projection.assumptions)
    assert "轉移" in joined
    assert str(int(TRANSFER_CAPTURE_RATE * 100)) in joined


def test_non_closed_incident_produces_no_transfer_risk(ctx):
    """路段沒封閉就沒有車流要轉移——回空是正確答案，不是失敗。"""
    incident = ctx["incident"].model_copy(update={"status": "Caution"})
    projection = project_risks(
        incident, ctx["route_plan"], ctx["sensing"], ctx["bundle"], 60
    )

    assert projection.risks == []
    assert projection.transferred_vehicles == 0


def test_no_route_plan_triggers_escalation(ctx):
    """沒有任何替代路線可用時，要明確說「單靠分流解決不了」並給升級建議。"""
    projection = project_risks(
        ctx["incident"], None, ctx["sensing"], ctx["bundle"], 90
    )

    assert projection.no_safe_route is True
    assert projection.escalation
    assert "大眾運輸" in projection.escalation


def test_projection_is_json_serialisable(ctx):
    """要能放進 DecisionResult 並回給前端。"""
    payload = projection_to_dict(_project(ctx))
    json.dumps(payload, ensure_ascii=False)
    assert payload["risks"]
    assert "assumptions" in payload


def test_risk_block_is_injectable_into_prompt(ctx):
    """給 LLM 讀的文字要包含時間、數值、對策三者。"""
    text = build_risk_block(_project(ctx))

    assert "後續風險推演" in text
    assert "對策：" in text
    assert "推演假設：" in text


def test_decision_result_carries_projection():
    """端到端：跑一次決策週期，`DecisionResult` 必須帶推演結果。"""
    import asyncio

    orchestrator.GATEWAY = orchestrator.build_gateway()
    orchestrator.reset()
    bundle = orchestrator.GATEWAY.load_data()
    incident = next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")

    result = asyncio.run(orchestrator.handle_incident(incident))

    assert result.projected_risks is not None, "決策結果沒有帶後續風險推演"
    assert result.projected_risks["risks"], "推演結果是空的"
    orchestrator.reset()
