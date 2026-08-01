"""推理鏈結構化輸出的回歸測試（`whatif_engine.build_judgment_steps` 等）。

這些函式在 2026-08-01 新增，用途是取代前端把 `judgment_basis` 純文字硬塞進
小灰字 div 的做法（換行與粗體全被吃掉，畫面上是一坨沒有斷點的文字）。
前端要畫比例條與改前改後對照，需要的是數值本身而不是描述數值的句子。

全部用真實 `data/` 資料跑，不用假資料——這幾個函式的價值就在於「顯示的數字
跟決策採用的數字是同一個」，用捏造的 bundle 測不出這件事。
"""

from __future__ import annotations

import json

import pytest

from src import orchestrator
from src.whatif_engine import (
    apply_scenario_overrides,
    build_data_snapshot,
    build_judgment_steps,
    compute_scenario,
    run_scenario,
)


@pytest.fixture(scope="module")
def gateway():
    orchestrator.GATEWAY = orchestrator.build_gateway()
    return orchestrator.GATEWAY


@pytest.fixture(scope="module")
def bundle(gateway):
    return gateway.load_data()


@pytest.fixture(scope="module")
def incident(bundle):
    return next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")


OVERRIDES = {"RD_TPE_004.saturation_score": 0.98}


def test_judgment_steps_has_all_stages(bundle, incident, gateway):
    """三個階段（命中條款／路線規劃／恢復時間）都要產出。"""
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle
    )

    stages = [s["stage"] for s in steps]
    assert stages == ["rules", "routes", "ete"]


def test_rule_items_carry_ratio_for_numeric_thresholds(bundle, incident, gateway):
    """數值型門檻要算出 ratio，前端才畫得出「實際值 vs 門檻」比例條。"""
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    # 一律傳 incident：少了它，關係分類認不出「事故路段連帶」，
    # 適用條款只會剩下 SOP-2（字串型 evidence），數值型的斷言就無從測起。
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle, incident
    )
    rules = next(s for s in steps if s["stage"] == "rules")

    numeric = [i for i in rules["items"] if isinstance(i.get("threshold"), (int, float))]
    assert numeric, "至少要有一條數值門檻的命中"
    for item in numeric:
        assert "ratio" in item
        assert item["ratio"] == pytest.approx(item["value"] / item["threshold"], rel=1e-3)


def test_rule_items_omit_ratio_for_string_thresholds(bundle, incident, gateway):
    """SOP-2 的 evidence 是 "Closed/Critical" 這種字串，沒有比例可言，
    不得硬算出一個假的 ratio 讓前端畫出無意義的長條。"""
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    # 一律傳 incident：少了它，關係分類認不出「事故路段連帶」，
    # 適用條款只會剩下 SOP-2（字串型 evidence），數值型的斷言就無從測起。
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle, incident
    )
    rules = next(s for s in steps if s["stage"] == "rules")

    string_hits = [i for i in rules["items"] if isinstance(i.get("threshold"), str)]
    assert string_hits, "ACC_001 應該命中 SOP-2（字串型 evidence）"
    for item in string_hits:
        assert "ratio" not in item


def test_entity_codes_resolved_to_display_names(bundle, incident, gateway):
    """RD_TPE_002 這種代碼要換成「光復南路」，指揮官不會背路段編號。"""
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    # 一律傳 incident：少了它，關係分類認不出「事故路段連帶」，
    # 適用條款只會剩下 SOP-2（字串型 evidence），數值型的斷言就無從測起。
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle, incident
    )
    rules = next(s for s in steps if s["stage"] == "rules")

    named = [i for i in rules["items"] if i["target"].startswith(("RD_", "BS_"))]
    assert named
    for item in named:
        assert item["target_name"] != item["target"], f"{item['target']} 沒有換成人話名稱"


def test_only_applicable_clauses_reach_the_answer(bundle, incident, gateway):
    """問答裡只送「適用條款」，不送全市掃描結果。

    [2026-08-01 契約變更] 這個測試以前斷言的是相反的事——「命中條款要全部
    送到前端」。改掉的理由是使用者連續三輪反映那份清單看不懂、沒有用：

        `evaluate_rules()` 掃全市是為了 **Dashboard 的態勢掌握**設計的，
        值班人員需要知道現在全市哪裡在燒。那個需求成立，但位置在 Dashboard。

        它會出現在問答裡，只是因為 What-if 重用了 `evaluate_rules()`，
        順手把 `rule_hits` 一起帶出來。對「如果仁愛路坍塌會怎樣」這個問題，
        全市另外 14 個地方超標從沒幫任何人做過決定，只是把真正重要的那一兩條
        擠到看不見的地方。

    現在只送決定處置鏈的主因、以及使用者自己假設的對象。
    """
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle, incident
    )
    rules = next(s for s in steps if s["stage"] == "rules")

    assert rules["title"] == "適用條款"
    assert len(rules["items"]) < len(outcome.sensing.rule_hits), (
        "問答裡不該再出現全市掃描結果"
    )
    assert all(
        i["relation"] in ("assumed", "primary", "related") for i in rules["items"]
    ), "有全市背景條款漏進答案裡"

    # 這些欄位是舊的「命中條款」介面，一併移除，避免前端還在讀
    for gone in ("total_hits", "collapse_after", "hidden_count", "relation_counts"):
        assert gone not in rules["extra"], f"{gone} 屬於已移除的命中條款介面"


def test_primary_clause_is_always_present(bundle, incident, gateway):
    """主因條款一定要在——它是「為什麼是這個結論」的答案本身。"""
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle, incident
    )
    rules = next(s for s in steps if s["stage"] == "rules")

    assert any(i["is_primary"] for i in rules["items"]), "主因條款不見了"
    assert rules["items"][0]["relation"] in ("assumed", "primary")


def test_evaluation_time_is_disclosed(bundle, incident, gateway):
    """評估時刻必須跟著答案走。

    同一條路在 22:10 與 23:30 是完全不同的世界（實測市民大道四段
    0.78 vs 0.98）。少了這個欄位，答案裡每個數字都無從追問。
    """
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    steps = build_judgment_steps(
        outcome.sensing, outcome.route_plan, outcome.ete, outcome.bundle, incident,
        as_of_reason=outcome.as_of_reason,
    )
    rules = next(s for s in steps if s["stage"] == "rules")

    assert rules["extra"]["as_of"] == "22:10"
    assert rules["extra"]["as_of_reason"] == "事故發生時刻"


def test_snapshot_uses_as_of_not_dataset_end(bundle, incident, gateway):
    """快照必須用事故當下的 as-of 值，不是整份資料的最後一筆。

    回歸測試：原本寫的是 `max(samples, key=timestamp)`。ACC_001 事故時間是
    22:10，但 RD_TPE_004 的資料一路到 22:45——快照會顯示 22:45 的 0.98，
    而規則引擎用的是 22:00 的 0.78。畫面上的數字跟決策採用的數字對不起來，
    使用者拿去比對門檻會發現兜不攏。
    """
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    snapshot = build_data_snapshot(
        outcome.bundle, OVERRIDES, incident, base=outcome.base_bundle
    )

    entry = snapshot["entities"]["RD_TPE_004"]
    assert entry["before"]["saturation_score"] == 0.78, "as-of 22:10 的值應該是 0.78"
    assert entry["saturation_score"] == 0.98, "覆寫後應該是 0.98"
    # 快照時間點不得晚於事故時間
    assert entry["snapshot_at"] <= incident.timestamp.isoformat()


def test_snapshot_before_absent_without_base(bundle, incident, gateway):
    """沒傳 base 時 `before` 留空，前端退化成只顯示現值，不得拋錯。"""
    outcome = compute_scenario(bundle, incident, OVERRIDES, gateway)
    snapshot = build_data_snapshot(outcome.bundle, OVERRIDES, incident, base=None)

    for entry in snapshot["entities"].values():
        assert "before" not in entry


def test_original_bundle_not_mutated_by_overrides(bundle):
    """覆寫只作用在記憶體副本，原始 bundle 不得被污染。

    這條沒過的話，同一個 session 問第二個 What-if 會拿到被前一次污染的基準值，
    而且完全沒有徵兆。
    """
    before = [s.saturation_score for s in bundle.traffic if s.segment_id == "RD_TPE_004"]
    apply_scenario_overrides(bundle, OVERRIDES)
    after = [s.saturation_score for s in bundle.traffic if s.segment_id == "RD_TPE_004"]

    assert before == after
    assert len(set(after)) > 1, "原始資料本來就有多種飽和度，全部相同代表被覆寫了"


def test_run_scenario_output_is_json_serialisable(bundle, incident, gateway):
    """Strands 會把工具回傳值 json.dumps 送回模型——夾帶 Pydantic 物件會直接炸。"""
    result = run_scenario(bundle, incident, OVERRIDES, gateway)

    json.dumps(result, ensure_ascii=False)  # 不拋例外即通過
    assert "judgment_steps" in result
    assert "current_data_snapshot" in result


def test_judgment_steps_and_basis_agree_on_level(bundle, incident, gateway):
    """結構化版與字串版是兩份輸出，但必須同源——等級不得分歧。"""
    result = run_scenario(bundle, incident, OVERRIDES, gateway)

    rules = next(s for s in result["judgment_steps"] if s["stage"] == "rules")
    level = rules["extra"]["traffic_level"]

    assert f"**交通分級**：{level}" in result["judgment_basis"]
