"""對話上下文的分流與時間一致性回歸測試。

[2026-08-02] 使用者連續回報的四件事，每一件都在這裡鎖住：

  「後續推演跟決策軌跡，在我問不相干的問題時會出現，例如問你是誰時出現」
      → test_chitchat_carries_no_projected_risks

  「如果現在手上有 report，chatbot 要熟悉這 report 並可以應付使用者加問；
    若沒有 report，也要給出預測，但要合乎我們的邏輯」
      → test_facts_context_uses_report_when_one_exists
      → test_facts_context_falls_back_to_ambient_when_no_report
      → test_report_branch_does_not_depend_on_current_trace_id

  「chatbot 沒有做到我的要求，可能跟時間有關」
      → test_scenario_as_of_follows_simulator_after_incident

  「所有這個系統的時間都統一模擬器的時間」
      → test_clock_now_follows_simulator
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import clock, orchestrator
from src.agent.response_formatter import W1Response
from src.agent.whatif_agent import (
    _current_incident_record,
    build_ambient_facts_block,
    build_facts_context,
    records_with_report,
)
from src.models import (
    DecisionResult,
    EteEstimate,
    Incident,
    IncidentSeverity,
    RouteCandidate,
    RoutePlan,
)
from src.orchestrator import IncidentRecord

_TZ = timezone(timedelta(hours=8))
_INCIDENT_AT = datetime(2026, 5, 20, 22, 10, tzinfo=_TZ)


@pytest.fixture(autouse=True)
def clean_state():
    """每個測試都從乾淨的 GlobalState 開始，並確保 GATEWAY 已初始化。

    `import main` 是必要的：`orchestrator.GATEWAY` 由 main 的 startup 掛上去，
    沒有它 `load_data()` 會在 None 上炸。
    """
    import main  # noqa: F401

    orchestrator.reset()
    orchestrator._current_trace_ctx.set(None)
    yield
    orchestrator.reset()
    orchestrator._current_trace_ctx.set(None)


def _seed_record(
    event_id: str = "E_TEST",
    trace_id: str = "TR-20260520-2210-0001",
    report: str | None = "【交控建議書】主線改走市民大道四段，預計 45 分鐘恢復。",
) -> IncidentRecord:
    """塞一起「已產出建議書」的進行中事件到 GlobalState。"""
    incident = Incident(
        event_id=event_id,
        type="Road_Collapse_Accident",
        location="光復南路與市民大道口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="路面坍塌，全線封閉",
        timestamp=_INCIDENT_AT,
    )
    decision = DecisionResult(
        trace_id=trace_id,
        triggered_by=["§2"],
        level="A",
        incident=incident,
        routes=RoutePlan(
            primary=RouteCandidate(
                segment_id="RD_TPE_004",
                name="市民大道四段",
                eligible=True,
                position="upstream",
                saturation_score=0.78,
                capacity_vph=2400,
                snapshot_at=_INCIDENT_AT,
            ),
            secondary=RouteCandidate(
                segment_id="RD_TPE_005",
                name="仁愛路四段",
                eligible=True,
                position="downstream",
                saturation_score=0.65,
                capacity_vph=1800,
                snapshot_at=_INCIDENT_AT,
            ),
            excluded=[],
            findings=[],
            candidates=[],
            selection_rule="SOP-2 §2a(3) 上游優先",
        ),
        ete=EteEstimate(
            minutes=45,
            recovery_at="2026-05-20 22:55",
            formula="60 + max(0,(0.78-0.5)*60) = 45",
            base_clearance=60,
            average_saturation=0.78,
        ),
        control_center_report=report,
        notifications=None,
        degraded=[],
        duration_ms=100,
        is_simulated=False,
    )
    record = IncidentRecord(
        trace_id=trace_id,
        incident=incident,
        decision_result=decision,
        bundle_snapshot=orchestrator.GATEWAY.load_data(),
    )
    orchestrator.get_global_state().active_incidents[event_id] = record
    return record


# ---------------------------------------------------------------------------
# #3 閒聊不得帶結構化附件
# ---------------------------------------------------------------------------


def test_chitchat_carries_no_projected_risks():
    """問「你是誰」不得跟著一張後續風險推演。

    `_attach_trace()` 原本是「只要有 trace_id 就掛推演」，於是閒聊底下會出現
    一張講著另一起事件的時間軸。使用者看到的是系統把問題聽成了別的東西。
    """
    record = _seed_record()

    reply = orchestrator._attach_trace(
        W1Response(intent_type="chitchat", summary="我是交通策略諮詢顧問。"),
        record.trace_id,
    )

    assert reply.projected_risks is None
    assert reply.trace_id == record.trace_id, "trace_id 仍要帶——那是對帳憑據"


def test_report_followup_is_not_classified_as_chitchat():
    """「這起事件該怎麼處理」不得被當成閒聊。

    `advisor.txt` 1-9 明文要求：已有建議書時直接引用、不要呼叫
    `simulate_scenario` 重算。於是這種追問一個工具都沒呼叫，而原本的規則
    `if not tools_called: intent_type = "chitchat"` 就把它標成閒聊——
    前端據此不畫任何東西，使用者問的是事件本身卻拿不到那張推演圖。
    """
    from src.agent.response_formatter import classify_no_tool_intent

    assert classify_no_tool_intent("這起事件該怎麼處理？") == "report_followup"
    assert classify_no_tool_intent("為什麼建議走仁愛路四段") == "report_followup"
    assert classify_no_tool_intent("改道之後會有什麼風險") == "report_followup"

    assert classify_no_tool_intent("你是誰") == "chitchat"
    assert classify_no_tool_intent("今天天氣如何") == "chitchat"
    assert classify_no_tool_intent("幫我寫首詩") == "chitchat"
    assert classify_no_tool_intent("") == "chitchat"
    assert classify_no_tool_intent(None) == "chitchat"


def test_report_followup_carries_projected_risks():
    """追問建議書時，該週期的風險推演要附上——那正是使用者要的答案。"""
    record = _seed_record()
    record.decision_result.projected_risks = {"risks": [{"segment_id": "RD_TPE_004"}]}

    reply = orchestrator._attach_trace(
        W1Response(intent_type="report_followup", summary="建議改走市民大道四段。"),
        record.trace_id,
    )

    assert reply.projected_risks is not None


def test_whatif_still_carries_projected_risks():
    """真的在做情境推演時，推演該掛的還是要掛——過濾不能把功能一起關掉。"""
    record = _seed_record()
    record.decision_result.projected_risks = {"risks": [{"segment_id": "RD_TPE_004"}]}

    reply = orchestrator._attach_trace(
        W1Response(intent_type="whatif_simulation", summary="重算結果如下。"),
        record.trace_id,
    )

    assert reply.projected_risks == {"risks": [{"segment_id": "RD_TPE_004"}]}


def test_reply_never_carries_trace_steps():
    """決策軌跡不再進對話（前端已拿掉那個區塊）。"""
    record = _seed_record()

    reply = orchestrator._attach_trace(
        W1Response(intent_type="whatif_simulation", summary="重算結果如下。"),
        record.trace_id,
    )

    assert reply.trace_steps == []


# ---------------------------------------------------------------------------
# #4 加問模式 vs 預測模式
# ---------------------------------------------------------------------------


def test_facts_context_falls_back_to_ambient_when_no_report():
    """Reports 裡一份都沒有 → 走預測模式，事實區塊是全市態勢。

    原本這種情況下事實區塊是 `None`，模型手上一個數字都沒有還被要求回答
    路況問題，只能編。
    """
    assert records_with_report() == []

    block = build_facts_context(_current_incident_record())

    assert block is not None, "沒有 report 時仍必須有事實可依據"
    assert "目前全市態勢" in block
    assert "沒有任何進行中的事件" in block
    assert "必須呼叫 simulate_scenario" in block, "前瞻問題仍不得自行外推"


def test_facts_context_uses_report_when_one_exists():
    """Reports 裡有 report → 走加問模式，建議書全文必須進 prompt。"""
    _seed_record()

    block = build_facts_context(_current_incident_record())

    assert block is not None
    assert "交控建議書" in block
    assert "主線改走市民大道四段" in block, "建議書全文沒有進事實區塊"
    assert "以本文為準" in block, "缺少『不要另外提出不同處置』的約束"
    assert "目前全市態勢" not in block, "有 report 時不該掉進預測模式"


def test_report_branch_does_not_depend_on_current_trace_id():
    """使用者的定案：不必確認他正在看哪一份，只要 Reports 有 report 就走加問。

    前端沒帶 `current_trace_id`（或帶了一個對不上的）時，原本會整個掉回
    「沒有任何事實」。現在 trace_id 只是消歧提示。
    """
    _seed_record()
    orchestrator._current_trace_ctx.set(None)

    assert _current_incident_record() is not None
    assert "交控建議書" in build_facts_context(_current_incident_record())

    orchestrator._current_trace_ctx.set("TR-DOES-NOT-EXIST")
    assert _current_incident_record() is not None, "對不上的 trace_id 也要退回最新那份"


def test_current_trace_id_disambiguates_between_events():
    """多起事件時，trace_id 要能指出使用者眼前是哪一份。"""
    _seed_record(event_id="E_A", trace_id="TR-20260520-2210-0001", report="A 事件建議書")
    _seed_record(event_id="E_B", trace_id="TR-20260520-2240-0002", report="B 事件建議書")

    orchestrator._current_trace_ctx.set("TR-20260520-2210-0001")
    assert _current_incident_record().trace_id == "TR-20260520-2210-0001"

    # 沒指定時取最新的那一份（trace_id 字串序即時間序）
    orchestrator._current_trace_ctx.set(None)
    assert _current_incident_record().trace_id == "TR-20260520-2240-0002"


def test_other_events_reports_are_attached_too():
    """多起事件時，其餘建議書也要在 prompt 裡——我們不知道長官問的是哪一起。"""
    _seed_record(event_id="E_A", trace_id="TR-20260520-2210-0001", report="A 事件建議書內容")
    _seed_record(event_id="E_B", trace_id="TR-20260520-2240-0002", report="B 事件建議書內容")

    orchestrator._current_trace_ctx.set("TR-20260520-2240-0002")
    block = build_facts_context(_current_incident_record())

    assert "B 事件建議書內容" in block
    assert "A 事件建議書內容" in block
    assert "現場共有 2 起進行中事件" in block


def test_incomplete_cycle_falls_back_to_ambient():
    """週期還沒跑到 PUSH（沒有 ETE）時給態勢，不給半套事實。

    半套事實比沒有事實更危險——模型會拿殘缺數字當完整的講。
    """
    record = _seed_record()
    record.decision_result.ete = None

    block = build_facts_context(record)

    assert "目前全市態勢" in block


def test_ambient_block_quotes_real_saturations():
    """態勢區塊的數字必須來自 `evaluate_rules` 的同一份資料，不是隨口寫的。"""
    block = build_ambient_facts_block()

    assert "評估時刻" in block
    assert "應變等級" in block
    assert "飽和度" in block


# ---------------------------------------------------------------------------
# #4c / #5 時間
# ---------------------------------------------------------------------------


def test_scenario_as_of_follows_simulator_after_incident(monkeypatch):
    """模擬器推進到事故之後，What-if 要跟著走，不能凍結在事故發生那一刻。

    這是「chatbot 沒有做到我的要求，可能跟時間有關」的根因：
    22:10 注入事故、模擬器跑到 23:10，Dashboard 顯示 23:10 的路況，
    chatbot 卻仍拿 22:10 回答。
    """
    from src import whatif_engine

    later = _INCIDENT_AT + timedelta(hours=1)
    monkeypatch.setattr(clock, "simulation_time", lambda: later)

    incident = _seed_record().incident
    bundle = orchestrator.GATEWAY.load_data()

    as_of, reason = whatif_engine.resolve_scenario_as_of(bundle, incident)

    assert as_of == later
    assert "模擬器當前時刻" in reason
    assert "22:10" in reason, "理由要講明事故發生時刻，否則使用者無從追問"


def test_scenario_as_of_never_goes_before_incident(monkeypatch):
    """模擬器被拉回事故之前時，仍用事故時刻。

    「事故發生前的事故現場」不是有意義的評估對象——那會讓規則引擎在事故還
    不存在的路況上套用事故條款。
    """
    from src import whatif_engine

    earlier = _INCIDENT_AT - timedelta(hours=2)
    monkeypatch.setattr(clock, "simulation_time", lambda: earlier)

    incident = _seed_record().incident
    bundle = orchestrator.GATEWAY.load_data()

    as_of, reason = whatif_engine.resolve_scenario_as_of(bundle, incident)

    assert as_of == _INCIDENT_AT
    assert reason == "事故發生時刻"


def test_clock_now_follows_simulator(monkeypatch):
    """模擬器在跑時，`clock.now()` 就是模擬器時刻。"""
    sim = datetime(2026, 5, 20, 22, 10, tzinfo=_TZ)
    monkeypatch.setattr(clock, "simulation_time", lambda: sim)

    assert clock.now() == sim
    assert clock.is_simulating() is True


def test_clock_now_falls_back_to_wall_clock(monkeypatch):
    """模擬器沒啟用時退回真實時間，且一定帶時區。

    naive datetime 混進來會在跟資料時間戳比較時拋 TypeError，而那種錯往往
    要到現場某個特定分支被走到才會出現。
    """
    monkeypatch.setattr(clock, "simulation_time", lambda: None)

    now = clock.now()

    assert now.tzinfo is not None
    assert clock.is_simulating() is False
