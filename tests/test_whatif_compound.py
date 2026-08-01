"""疊加情境：進行中事件之上再加一個假設。

守的是這個 bug——它讓 chatbot 看起來完全不可信：

    ACC_001（光復南路封閉）進行中，使用者問「如果延吉街封閉會怎樣」
      → 適用條款：SOP-2 **光復南路**、SOP-1 光復南路、SOP-7 光復南路
      → 路線規劃：**光復南路**的替代路線
      → ETE：**光復南路**的 90 分鐘
      → 建議動作：全部關於光復南路

    使用者問延吉街，系統從頭到尾回答光復南路，而且語氣完全肯定。

根因是 `run_scenario()` 的閘門寫成 `if incident is None` ——只有「沒有進行中
事件」時才把封閉假設合成成假想事故。有事件時假設對規則引擎完全空轉
（SOP-1 只看飽和度、SOP-2 綁在既有 incident 上）。

正確的閘門是「假設對象**是不是現有事件本身**」，而不是「有沒有事件」。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import orchestrator
from src.models import RouteRequest
from src.whatif_engine import run_scenario

CLOSE_YANJI = {"RD_TPE_008.lane_status": "Closed"}   # 延吉街
CLOSE_GUANGFU = {"RD_TPE_002.lane_status": "Closed"}  # 光復南路 = ACC_001 本身


@pytest.fixture(scope="module")
def gw():
    orchestrator.GATEWAY = orchestrator.build_gateway()
    return orchestrator.GATEWAY


@pytest.fixture(scope="module")
def bundle(gw):
    return gw.load_data()


@pytest.fixture(scope="module")
def acc001(bundle):
    return next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")


def _rules(result):
    return next(s for s in result["judgment_steps"] if s["stage"] == "rules")


def test_assumption_is_not_swallowed_by_active_incident(bundle, gw, acc001):
    """核心：有進行中事件時，對**別條路**的假設仍必須被計算。"""
    result = run_scenario(bundle, acc001, CLOSE_YANJI, gw, "如果延吉街封閉會怎樣")

    hypo = result.get("hypothetical_incident")
    assert hypo is not None, "假設被現有事件蓋掉了，完全沒有合成假想事故"
    assert hypo["segment_id"] == "RD_TPE_008"
    assert "延吉街" in hypo["segment_name"]


def test_applicable_clauses_are_about_the_assumed_road(bundle, gw, acc001):
    """適用條款要講延吉街，不是光復南路。"""
    result = run_scenario(bundle, acc001, CLOSE_YANJI, gw, "如果延吉街封閉會怎樣")
    items = _rules(result)["items"]

    assert items, "適用條款是空的"
    targets = {i["target"] for i in items}
    assert "RD_TPE_008" in targets, "延吉街完全沒有出現在適用條款裡"
    assert targets == {"RD_TPE_008"}, f"混進了與問題無關的路段：{targets - {'RD_TPE_008'}}"


def test_base_incident_is_disclosed(bundle, gw, acc001):
    """疊加時必須講明基準事件，否則使用者會以為系統忘了那起真實事件。"""
    result = run_scenario(bundle, acc001, CLOSE_YANJI, gw, "如果延吉街封閉會怎樣")
    base = result["hypothetical_incident"]["base_incident"]

    assert base is not None, "沒有交代這是疊加在哪起事件之上"
    assert base["event_id"] == "TPE_2026_ACC_001"
    assert base["segment_id"] == "RD_TPE_002"


def test_base_incident_segment_is_excluded_from_routes(bundle, gw, acc001):
    """基準事件封閉的路段不得被推薦成替代路線。

    延吉街的 alternatives 只有一條：光復南路。而光復南路正是 ACC_001 封閉的
    路段——所以正確答案是「無可行替代路線」，不是「改道走光復南路」。
    把一條剛剛才確認封閉的路推薦出去，是這類系統最危險的失敗模式。
    """
    result = run_scenario(bundle, acc001, CLOSE_YANJI, gw, "如果延吉街封閉會怎樣")
    rp = result.get("route_plan") or {}

    primary = (rp.get("primary") or {}).get("segment_id")
    secondary = (rp.get("secondary") or {}).get("segment_id")
    assert primary != "RD_TPE_002", "把 ACC_001 已封閉的光復南路推薦成主線了"
    assert secondary != "RD_TPE_002", "把 ACC_001 已封閉的光復南路推薦成次線了"

    excluded = {c["segment_id"]: c["reason_code"] for c in rp.get("excluded", [])}
    assert excluded.get("RD_TPE_002") == "CLOSED"


def test_ete_belongs_to_the_assumed_incident(bundle, gw, acc001):
    """ETE 要算延吉街的，不是照搬光復南路的 90 分。"""
    result = run_scenario(bundle, acc001, CLOSE_YANJI, gw, "如果延吉街封閉會怎樣")
    ete = result.get("ete")

    assert ete is not None
    assert ete["minutes"] != 90, "ETE 仍是光復南路那一份（90 分）"


def test_assuming_the_current_incident_itself_does_not_synthesize(bundle, gw, acc001):
    """假設的對象**就是**現有事件時，不該再合成一個假想事故。

    「如果光復南路封閉」而光復南路本來就因 ACC_001 封閉——使用者是在
    調整這起事件的條件，照原路徑重算即可，不是新增一起事故。
    """
    result = run_scenario(bundle, acc001, CLOSE_GUANGFU, gw, "如果光復南路封閉會怎樣")

    assert result.get("hypothetical_incident") is None
    items = _rules(result)["items"]
    assert any(i["is_primary"] for i in items), "應該仍以 ACC_001 為主因"


def test_extra_closed_segments_reach_route_planning(bundle, gw, acc001):
    """`RouteRequest.extra_closed_segments` 要真的被 plan_route 採用。"""
    from src.routing import plan_route

    plain = plan_route(RouteRequest(incident=acc001, bundle=bundle, as_of=acc001.timestamp))
    assert plain.primary is not None
    blocked_id = plain.primary.segment_id

    # 把原本的主線也標成封閉，它就不該再是主線
    blocked = plan_route(RouteRequest(
        incident=acc001, bundle=bundle, as_of=acc001.timestamp,
        extra_closed_segments=[blocked_id],
    ))
    assert (blocked.primary is None) or (blocked.primary.segment_id != blocked_id)
    reasons = {c["segment_id"] if isinstance(c, dict) else c.segment_id:
               (c["reason_code"] if isinstance(c, dict) else c.reason_code)
               for c in blocked.excluded}
    assert reasons.get(blocked_id) == "CLOSED"


def test_intersection_relaxed_finding_is_a_valid_code(bundle, gw):
    """回歸測試：`INTERSECTION_FILTER_RELAXED` 必須是合法的 FindingCode。

    上一次處理合併衝突時加了這個 finding 卻沒同步進 `FindingCode` Literal，
    於是只要走到「放寬直接相鄰篩選」就拋 ValidationError，**整個路線規劃崩掉**。
    15 條路段裡有 10 條會踩到（延吉街就是其中之一），而既有測試全部用 ACC_001
    ——它剛好是篩選能正常運作的那 5 條之一，所以完全沒被擋下來。
    """
    from src.models import RouteFinding

    # 建得起來就代表 Literal 收了這個值
    f = RouteFinding(
        finding_code="INTERSECTION_FILTER_RELAXED", segment_ids=["RD_TPE_006"], evidence={}
    )
    assert f.finding_code == "INTERSECTION_FILTER_RELAXED"

    # 端到端：對延吉街做假設不得崩潰
    result = run_scenario(bundle, None, CLOSE_YANJI, gw, "如果延吉街封閉")
    assert result.get("hypothetical_incident") is not None
