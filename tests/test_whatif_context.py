"""What-if 的「評估時刻」與「命中條款關係分類」回歸測試。

守的是同一個病：**系統幫使用者挑了一個他不知道的預設值**，然後產出一個
他無法解釋的畫面。實測長這樣：

    使用者在畫面上看 22:10 的事故，問「如果市民大道四段封閉會怎樣」
    → 前端沒帶 trace_id → incident=None
    → as_of 悄悄跳到 23:30（資料集最後一筆，跟畫面差 80 分鐘）
    → 那個時刻全市 15 條路段有 10 條 ≥0.85
    → 畫面顯示「共 15 條（全市其他地方 15）」

那 15 條跟使用者的假設完全無關，而且連他剛剛假設的那條路都被標成
「全市其他地方・與本事故無因果關係」——在根本沒有事故的情況下。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import orchestrator
from src.whatif_engine import compute_scenario, resolve_scenario_as_of, scenario_to_dict

OVERRIDES = {"RD_TPE_004.lane_status": "Closed"}


@pytest.fixture(scope="module")
def gw():
    orchestrator.GATEWAY = orchestrator.build_gateway()
    return orchestrator.GATEWAY


@pytest.fixture(scope="module")
def bundle(gw):
    return gw.load_data()


@pytest.fixture(scope="module")
def incident(bundle):
    return next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")


def _rules_extra(bundle, incident, gw, overrides=OVERRIDES):
    out = scenario_to_dict(compute_scenario(bundle, incident, overrides, gw), overrides, incident)
    step = next(s for s in out["judgment_steps"] if s["stage"] == "rules")
    return step["extra"], step["items"]


# --- 1A：評估時刻 -----------------------------------------------------------


def test_as_of_uses_incident_time_when_available(bundle, incident, gw):
    """有事故時，用事故發生時刻——使用者問的就是這起事故的假設情境。"""
    extra, _ = _rules_extra(bundle, incident, gw)
    assert extra["as_of"] == "22:10"
    assert extra["as_of_reason"] == "事故發生時刻"


def test_as_of_falls_back_to_simulator_time(bundle, incident, gw, monkeypatch):
    """沒有事故但模擬器在跑時，用模擬器時刻——那才是使用者畫面上的時間。

    這一支是本次修正的重點。原本沒有事故就直接掉到「資料集最新時刻」，
    使用者看著 22:10 卻拿到 23:30 的答案。
    """
    import main

    monkeypatch.setitem(main._simulation_state, "enabled", True)
    monkeypatch.setitem(main._simulation_state, "current_time", incident.timestamp)

    resolved, reason = resolve_scenario_as_of(bundle, None)
    assert resolved == incident.timestamp
    assert reason == "模擬器當前時刻"

    extra, _ = _rules_extra(bundle, None, gw)
    assert extra["as_of"] == "22:10"


def test_as_of_last_resort_is_latest_data(bundle, gw):
    """兩者都沒有時才用資料集最新時刻——而且必須說出來。"""
    _resolved, reason = resolve_scenario_as_of(bundle, None)
    assert reason == "資料集最新時刻"

    extra, _ = _rules_extra(bundle, None, gw)
    assert extra["as_of_reason"] == "資料集最新時刻"
    assert extra["as_of"], "評估時刻一定要回到畫面上，否則命中數無從理解"


def test_as_of_is_always_disclosed(bundle, incident, gw):
    """不管走哪一支，時刻與理由都必須帶出去。

    這是本次修正的核心原則：任何「系統幫你挑了一個你不知道的值」都會製造
    無法解釋的畫面。挑什麼可以討論，不講出來不行。
    """
    for inc in (incident, None):
        extra, _ = _rules_extra(bundle, inc, gw)
        assert extra["as_of"] is not None
        assert extra["as_of_reason"] is not None


# --- 1B：命中條款的關係分類 --------------------------------------------------


def test_assumed_target_is_not_labelled_background(bundle, gw):
    """使用者假設的對象不得被標成「全市其他地方」。

    這是最離譜的那個症狀：使用者剛剛假設市民大道四段封閉，系統把它跟
    城市另一頭的無關壅塞歸成同一類。
    """
    _extra, items = _rules_extra(bundle, None, gw)

    assumed = [i for i in items if i["target"] == "RD_TPE_004"]
    if assumed:  # 該時刻若有命中，必須標成假設對象
        assert all(i["relation"] == "assumed" for i in assumed)


def test_assumed_targets_sort_first(bundle, gw):
    """使用者關心的排最上面。"""
    _extra, items = _rules_extra(bundle, None, gw)
    relations = [i["relation"] for i in items]
    if "assumed" in relations:
        assert relations[0] == "assumed"


def test_city_wide_background_never_reaches_the_answer(bundle, incident, gw):
    """全市其他地方的超標一律不進答案。

    [2026-08-01 契約變更] 這個測試以前叫 `test_incident_hits_split_into_three_classes`，
    斷言三類都出現在 `items` 裡。現在背景那一類整個不送——它屬於 Dashboard 的
    態勢掌握，不屬於「這起事件怎麼辦」的答案。
    """
    _extra, items = _rules_extra(bundle, incident, gw)

    assert items, "適用條款不該是空的"
    assert all(i["relation"] != "background" for i in items), "全市背景漏進答案裡"
    assert sum(1 for i in items if i["relation"] == "primary") == 1, "SOP-2 應為唯一主因"
    assert any(i["relation"] == "related" for i in items), "事故路段連帶應該保留"
    assert items[0]["relation"] == "primary"


def test_has_incident_flag_drives_wording(bundle, incident, gw):
    """沒有事故時前端不能說「與本事故無因果關係」——那句話不成立。"""
    extra_with, _ = _rules_extra(bundle, incident, gw)
    extra_without, _ = _rules_extra(bundle, None, gw)

    assert extra_with["has_incident"] is True
    assert extra_without["has_incident"] is False


def test_assumption_without_any_hit_is_reported(bundle, gw, monkeypatch):
    """假設的對象一條規則都沒觸發時要明說，不能讓使用者自己猜。

    實測情境：模擬器停在 22:10，假設市民大道四段封閉。SOP-1 看飽和度
    （該時刻 0.78，未達 0.85）、SOP-2 需要 incident，所以一條都不觸發。
    畫面上只剩「全市其他地方」，使用者無從得知自己假設的那條路怎麼了。
    """
    import main

    incident_time = next(
        i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001"
    ).timestamp
    monkeypatch.setitem(main._simulation_state, "enabled", True)
    monkeypatch.setitem(main._simulation_state, "current_time", incident_time)

    extra, _items = _rules_extra(bundle, None, gw)
    assert "RD_TPE_004" in extra["assumed_no_hit"]


def test_removed_hit_count_fields_stay_removed(bundle, incident, gw):
    """舊的「命中條款」介面欄位不得復活。

    使用者明確要求「確保不要再有命中條款」。`total_hits`／`relation_counts`／
    `collapse_after` 都是那份清單的介面，留著會讓人以為還可以把它畫回來。
    """
    for inc in (incident, None):
        extra, items = _rules_extra(bundle, inc, gw)
        for gone in ("total_hits", "relation_counts", "collapse_after", "hidden_count"):
            assert gone not in extra, f"{gone} 是已移除的命中條款介面"
        assert all(i["relation"] != "background" for i in items)
