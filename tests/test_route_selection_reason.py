"""路線選擇的「為什麼是這條」必須可追溯。

守的是這個缺口：長官看到建議書後最自然的追問是

    「為什麼建議走市民大道四段？仁愛路四段不是比較空嗎？」

ACC_001 的實際數字讓這個問題非答不可：

    主線 市民大道四段  飽和度 0.78  ← 比較塞
    次線 仁愛路四段    飽和度 0.65  ← 比較空

正確答案是 SOP-2 §2a(3) 的**上游優先**（市民大道在上游、仁愛路在下游）。
但這條規則以前只存在於 `plan_route()` 的 `sort_key` 區域函式裡，沒有任何管道
離開那個函式——不在 `RoutePlan`、不在事實區塊、也不在畫面上。

於是 chatbot 只能列出「誰被排除」，答不出「為什麼選這條」。
對指揮決策系統來說，講不出理由的建議等於沒有建議。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import orchestrator
from src.models import RouteRequest
from src.reporting import build_facts_block


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


@pytest.fixture(scope="module")
def plan(gw, bundle, acc001):
    return gw.plan_routes(
        RouteRequest(incident=acc001, bundle=bundle, as_of=acc001.timestamp)
    )


def test_candidates_carry_position(plan):
    """每個合格候選都要標明相對事故點的位置——那是排序的第一順位依據。"""
    assert plan.primary is not None and plan.secondary is not None
    assert plan.primary.position is not None, "主線沒有位置資訊"
    assert plan.secondary.position is not None, "次線沒有位置資訊"


def test_acc001_primary_is_upstream_despite_higher_saturation(plan):
    """本測試的前提：主線飽和度確實比次線高。

    如果哪天資料變了、主線剛好也是最空的那條，這個測試就失去意義——
    所以前提本身要斷言，失敗時要看得出是資料變了而不是邏輯壞了。
    """
    assert plan.primary.position == "upstream"
    assert plan.secondary.position == "downstream"
    assert plan.primary.saturation_score > plan.secondary.saturation_score, (
        "資料已變：主線不再比次線塞，本測試的前提消失"
    )


def test_selection_rule_explains_the_counterintuitive_choice(plan):
    """`selection_rule` 必須直接回答「為什麼不走比較空的那條」。"""
    rule = plan.selection_rule
    assert rule, "RoutePlan 沒有帶選擇規則"

    assert "上游" in rule, "沒有講出上游優先這條關鍵規則"
    assert plan.primary.name in rule
    assert plan.secondary.name in rule
    assert "SOP-2" in rule, "沒有標明依據哪條 SOP"
    # 次線比較空這件事要被明確承認，而不是迴避
    assert str(plan.secondary.saturation_score) in rule


def test_no_feasible_route_says_so_plainly(gw, bundle, acc001):
    """完全沒有可行路線時，選擇規則要直說，不要留空字串。"""
    from src.routing import plan_route

    blocked = plan_route(RouteRequest(
        incident=acc001, bundle=bundle, as_of=acc001.timestamp,
        extra_closed_segments=[c.segment_id for c in bundle.road_network],
    ))
    assert blocked.primary is None
    assert blocked.selection_rule
    assert "無可行" in blocked.selection_rule


def test_facts_block_carries_selection_reasoning(bundle, acc001, gw, plan):
    """事實區塊要帶選擇規則與位置——這是 chatbot 回答追問的唯一材料來源。

    少了它，模型面對「為什麼是這條」只能猜。而猜出來的理由聽起來一樣肯定，
    使用者無從分辨。
    """
    sensing = gw.evaluate_rules(bundle, acc001)
    ete = gw.calculate_ete(acc001, bundle)
    facts = build_facts_block(acc001, sensing, plan, ete, bundle)

    assert "路線選擇規則" in facts, "事實區塊沒有帶選擇規則"
    assert "上游" in facts
    # 兩條路線的飽和度都要在，模型才比較得出來
    assert str(plan.primary.saturation_score) in facts
    assert str(plan.secondary.saturation_score) in facts
