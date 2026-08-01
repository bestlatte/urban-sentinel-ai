"""「如果某某路封閉」的完整鏈路測試。

守的是這個 bug：使用者的封閉假設**對規則引擎完全空轉**。

    lane_status = "Closed" 改下去
      SOP-1  只看 saturation_score  → 不理
      SOP-2  需要 Incident 物件      → 不觸發
      SOP-3~7 與路段封閉無關
    → 一條規則都沒反應
    → 路線重規劃與 ETE 也拿不到（兩者都要 incident）
    → 畫面上只剩該時刻全市既有的十幾條背景命中

使用者的原話是「每次給我就是全部 15 條」。那不是顯示層的問題，是這個假設
從來沒有真的被計算過。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import orchestrator
from src.whatif_engine import (
    SEVERITY_LADDER,
    closure_targets,
    detect_severity,
    run_scenario,
    synthesize_incident,
)

CLOSE_004 = {"RD_TPE_004.lane_status": "Closed"}


@pytest.fixture(scope="module")
def gw():
    orchestrator.GATEWAY = orchestrator.build_gateway()
    return orchestrator.GATEWAY


@pytest.fixture(scope="module")
def bundle(gw):
    return gw.load_data()


def _run(bundle, gw, question, overrides=CLOSE_004):
    return run_scenario(bundle, None, overrides, gw, question)


# --- 封閉偵測與合成 ---------------------------------------------------------


def test_closure_targets_detects_closed_and_blocked():
    assert closure_targets({"RD_TPE_004.lane_status": "Closed"}) == ["RD_TPE_004"]
    assert closure_targets({"RD_TPE_004.lane_status": "Blocked"}) == ["RD_TPE_004"]
    # 沒封閉、或改的是別的欄位，都不該合成事故
    assert closure_targets({"RD_TPE_004.lane_status": "Open"}) == []
    assert closure_targets({"RD_TPE_004.saturation_score": 0.98}) == []
    assert closure_targets({"BS_MRT_BL17.user_count": 40000}) == []


def test_synthesized_incident_is_clearly_marked(bundle):
    """假想事故必須一眼可辨，不能被誤認為真實事件。"""
    from datetime import datetime, timezone, timedelta

    as_of = datetime(2026, 5, 20, 22, 10, tzinfo=timezone(timedelta(hours=8)))
    inc = synthesize_incident(bundle, "RD_TPE_004", "Critical", as_of)

    assert inc.event_id.startswith("WHATIF_")
    assert "假設" in inc.description
    assert inc.affected_segment == "RD_TPE_004"
    assert inc.status == "Closed"


def test_closure_now_triggers_sop2_and_full_chain(bundle, gw):
    """核心主張：封閉假設要讓整條「推演 → 解方」鏈跑起來。

    這是使用者的目標——「看我們有的規則，推演後給出解方」。
    """
    result = _run(bundle, gw, "如果市民大道四段發生嚴重車禍封閉會怎樣")

    step = next(s for s in result["judgment_steps"] if s["stage"] == "rules")
    clauses = {i["clause_id"] for i in step["items"] if i["target"] == "RD_TPE_004"}
    assert "SOP-2" in clauses, "封閉假設沒有觸發 SOP-2，鏈路仍是斷的"

    assert result.get("route_plan"), "沒有算出改道路線"
    assert result.get("ete"), "沒有算出 ETE"
    assert result.get("risk_projection"), "沒有跑二階風險推演"


def test_assumed_target_hits_are_focused(bundle, gw):
    """適用條款只留使用者假設的對象，全市其他地方完全不進答案。"""
    result = _run(bundle, gw, "如果市民大道四段發生嚴重車禍封閉會怎樣")
    step = next(s for s in result["judgment_steps"] if s["stage"] == "rules")

    assert step["title"] == "適用條款"
    assert step["items"], "適用條款不該是空的"
    assert step["items"][0]["relation"] == "assumed"
    assert all(i["relation"] != "background" for i in step["items"])


# --- 嚴重度（使用者選定的方案 C）--------------------------------------------


def test_severity_keywords_never_match_road_names():
    """回歸測試：單字關鍵字會被路名吃掉。

    第一版把「大」放進 High，結果「市民**大**道」讓每個問題都被判 High——
    連「輕微擦撞」都一樣。ETE 因此差 40 分鐘，而畫面上沒有任何跡象。
    """
    assert detect_severity("如果市民大道四段封閉會怎樣") is None
    assert detect_severity("如果市民大道四段輕微擦撞封閉") == "Medium"
    assert detect_severity("如果市民大道四段發生嚴重車禍") == "Critical"
    assert detect_severity("敦化南路一段封閉") is None


def test_unspecified_severity_lists_all_three(bundle, gw):
    """沒指定嚴重度時並列三種，而不是偷偷挑一個。"""
    result = _run(bundle, gw, "如果市民大道四段封閉會怎樣")

    opts = result.get("severity_options")
    assert opts, "沒有給嚴重度對照表"
    assert [o["severity"] for o in opts] == list(SEVERITY_LADDER)

    etes = [o["ete_minutes"] for o in opts]
    assert len(set(etes)) == 3, f"三種嚴重度應該有不同 ETE，實際 {etes}"
    assert etes == sorted(etes, reverse=True), "ETE 應該由重到輕遞減"

    assert result["hypothetical_incident"]["severity_stated"] is False


def test_stated_severity_skips_the_comparison(bundle, gw):
    """使用者講明了就不用給選項——沒有東西要挑。"""
    result = _run(bundle, gw, "如果市民大道四段發生嚴重車禍封閉會怎樣")

    assert not result.get("severity_options")
    assert result["hypothetical_incident"]["severity_stated"] is True
    assert result["severity"] == "Critical"


def test_medium_severity_correctly_fails_sop2_threshold(bundle, gw):
    """SOP-2 明訂 severity 需為 High|Critical——Medium 不該觸發。

    這條守的是「假想事故不得繞過規則本身的門檻」。合成事故只是補上
    規則引擎需要的輸入，不是幫使用者的假設開後門。
    """
    result = _run(bundle, gw, "如果市民大道四段輕微擦撞封閉")
    step = next(s for s in result["judgment_steps"] if s["stage"] == "rules")
    clauses = {i["clause_id"] for i in step["items"] if i["target"] == "RD_TPE_004"}

    assert result["severity"] == "Medium"
    assert "SOP-2" not in clauses


def test_non_closure_assumption_is_unaffected(bundle, gw):
    """非封閉假設不該被合成事故影響——原路徑照舊。"""
    result = run_scenario(
        bundle, None, {"BS_MRT_BL17.user_count": 40000}, gw, "如果BL17到四萬人"
    )
    assert result.get("hypothetical_incident") is None
    assert result.get("severity_options") in (None, [])


def test_evaluation_time_always_disclosed(bundle, gw):
    """假想事故的評估時刻必須講出來——它會改變所有下游數字。"""
    result = _run(bundle, gw, "如果市民大道四段封閉會怎樣")
    hypo = result["hypothetical_incident"]

    assert hypo["as_of"]
    assert hypo["as_of_reason"]
