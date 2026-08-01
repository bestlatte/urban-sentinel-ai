"""A2 編排規劃器測試（SPEC-O2 §6 驗收表 #1-#4 + 護欄單元測試）。

規劃器本身是 LLM，測試一律以 mock 取代 Agent 實例——SPEC-O2 §6 開宗明義要求
「決定性，模組以 mock 代替」，測試不得依賴真實 Bedrock 呼叫。

黃金值來源 SPEC-00 §5：ACC_001 主線 RD_TPE_004 / 次線 RD_TPE_005 / ETE 90 分。
"""

import asyncio
import json
import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src.agent import a2_orchestrator_agent as a2
from src.models import ToolName


def setup_module():
    from src import orchestrator

    if orchestrator.GATEWAY is None:
        orchestrator.GATEWAY = orchestrator.build_gateway()


# ---------------------------------------------------------------------------
# 測試輔助
# ---------------------------------------------------------------------------


SOP2_CLASSIFICATION = {
    "primary_sop": "SOP-2",
    "requires_rerouting": True,
    "affected_source": "RD_TPE_002",
}

FULL_SOP2_PLAN = {
    "steps": [
        {"tool": "RAG_SEARCH"},
        {"tool": "GRAPH_BUILD"},
        {"tool": "UPSTREAM_JUDGE"},
        {"tool": "CANDIDATE_FILTER"},
        {"tool": "ROUTE_SELECT"},
        {"tool": "CALC_ETE"},
        {"tool": "FORMAT_REPORT"},
    ]
}


class FakeAgent:
    """代替 Strands Agent：記錄呼叫次數，回傳預設好的字串。"""

    def __init__(self, response: str, delay: float = 0.0):
        self._response = response
        self._delay = delay
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        if self._delay:
            import time

            time.sleep(self._delay)
        return self._response


@pytest.fixture(autouse=True)
def _reset_agent_cache():
    a2.reset_agent_cache()
    yield
    a2.reset_agent_cache()


@pytest.fixture(autouse=True)
def _stub_w1_advisory(monkeypatch):
    """把 GATEWAY.run_agent（W1 建議）換成 stub。

    本檔測的是 A2 編排，不是 W1。週期測試會把 USE_BEDROCK 設成 true 好讓 A2 的
    LLM 路徑生效，但那同時也會讓 `LiveGateway.run_agent` 真的去呼叫 Bedrock，
    使整個測試套件依賴網路與憑證。這裡切斷該分支，讓測試維持決定性。
    """
    from src import orchestrator

    if orchestrator.GATEWAY is None:
        orchestrator.GATEWAY = orchestrator.build_gateway()

    stub = orchestrator.StubGateway()
    monkeypatch.setattr(
        type(orchestrator.GATEWAY),
        "run_agent",
        lambda self, incident, sensing, route_plan, ete: stub.run_agent(
            incident, sensing, route_plan, ete
        ),
        raising=False,
    )

    # C1-C4 生成（reporting）與 M4B 解釋鏈都走這一個 Bedrock 出口，
    # 攔在這裡就能讓整個決策週期離線可測，而不必逐一 patch 各生成函式。
    from src import reporting

    monkeypatch.setattr(
        reporting,
        "_invoke_bedrock_converse",
        lambda system_prompt, user_message: "【測試用生成內容】",
    )


def _install_agent(monkeypatch, agent):
    """裝上假 Agent 並開啟 USE_BEDROCK。

    模組頂端把 USE_BEDROCK 預設成 false（保底模式），但凡是要測「LLM 規劃路徑」
    的案例都必須讓旗標為 true，否則 `plan_tools()` 會在送出請求前就先降級。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")
    monkeypatch.setattr(a2, "_get_a2_agent", lambda: agent)
    return agent


def _load_incident(event_id="TPE_2026_ACC_001"):
    from src import orchestrator

    bundle = orchestrator.GATEWAY.load_data()
    for inc in bundle.incidents:
        if inc.event_id == event_id:
            return inc
    raise AssertionError(f"測試資料缺少事件 {event_id}")


# ---------------------------------------------------------------------------
# 護欄①：白名單驗證（SPEC-O2 §3.2-1）
# ---------------------------------------------------------------------------


def test_parse_tool_plan_accepts_valid_json():
    plan = a2.parse_tool_plan(json.dumps(FULL_SOP2_PLAN))
    assert plan.tool_names()[0] is ToolName.RAG_SEARCH
    assert ToolName.CALC_ETE in plan.tool_names()


def test_parse_tool_plan_strips_markdown_fence():
    text = "```json\n" + json.dumps(FULL_SOP2_PLAN) + "\n```"
    assert len(a2.parse_tool_plan(text).steps) == 7


def test_parse_tool_plan_tolerates_surrounding_prose():
    text = "好的，以下是計畫：\n" + json.dumps(FULL_SOP2_PLAN) + "\n希望有幫助。"
    assert len(a2.parse_tool_plan(text).steps) == 7


def test_parse_tool_plan_rejects_illegal_tool_name():
    """非法工具名 → 整份計畫作廢，不做部分採用。"""
    bad = {"steps": [{"tool": "RAG_SEARCH"}, {"tool": "DROP_DATABASE"}]}
    with pytest.raises(ValueError, match="白名單"):
        a2.parse_tool_plan(json.dumps(bad))


def test_parse_tool_plan_rejects_empty_steps():
    with pytest.raises(ValueError):
        a2.parse_tool_plan(json.dumps({"steps": []}))


def test_parse_tool_plan_rejects_non_json():
    with pytest.raises(ValueError):
        a2.parse_tool_plan("我不知道要呼叫什麼工具")


def test_args_hint_is_not_authoritative():
    """SPEC-00 鐵律①：args_hint 只留痕，不得成為事實來源。"""
    plan = a2.parse_tool_plan(
        json.dumps({"steps": [{"tool": "CALC_ETE", "args_hint": {"minutes": 999}}]})
    )
    assert plan.steps[0].args_hint == {"minutes": 999}
    # 型別層面不承諾任何數值語意——執行時 orchestrator 一律自 bundle 取值
    assert plan.steps[0].tool is ToolName.CALC_ETE


# ---------------------------------------------------------------------------
# 護欄②：必要步驟檢查（SPEC-O2 §3.2-2）
# ---------------------------------------------------------------------------


def test_required_steps_pass_for_complete_sop2_plan():
    plan = a2.parse_tool_plan(json.dumps(FULL_SOP2_PLAN))
    assert a2.check_required_steps(plan, "SOP-2") is None


def test_required_steps_detect_missing_calc_ete():
    steps = [s for s in FULL_SOP2_PLAN["steps"] if s["tool"] != "CALC_ETE"]
    plan = a2.parse_tool_plan(json.dumps({"steps": steps}))
    assert "CALC_ETE" in a2.check_required_steps(plan, "SOP-2")


def test_required_steps_detect_missing_r_chain():
    steps = [s for s in FULL_SOP2_PLAN["steps"] if s["tool"] != "ROUTE_SELECT"]
    plan = a2.parse_tool_plan(json.dumps({"steps": steps}))
    reason = a2.check_required_steps(plan, "SOP-2")
    assert "R 鏈" in reason and "ROUTE_SELECT" in reason


def test_required_steps_sop5_needs_count_intersections():
    plan = a2.parse_tool_plan(json.dumps({"steps": [{"tool": "CALC_ETE"}]}))
    assert "COUNT_INTERSECTIONS" in a2.check_required_steps(plan, "SOP-5")


def test_required_steps_sop3_has_no_mandatory_tools():
    """§3 事件 spec 未規定必要步驟，不得強制。"""
    plan = a2.parse_tool_plan(json.dumps({"steps": [{"tool": "CALC_ETE"}]}))
    assert a2.check_required_steps(plan, "SOP-3") is None


# ---------------------------------------------------------------------------
# 護欄③：逾時（SPEC-O2 §3.2-3、§4.3 預算 8s）
# ---------------------------------------------------------------------------


def test_planner_times_out(monkeypatch):
    _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN), delay=0.5))
    result = a2.plan_tools(
        "TPE_2026_ACC_001", "Road_Collapse_Accident", SOP2_CLASSIFICATION, timeout_s=0.05
    )
    assert result.degraded and "逾時" in result.reason


def test_planner_never_calls_bedrock_in_fallback_mode(monkeypatch):
    """00-tech-stack.md §6：USE_BEDROCK=false 時不得送出任何 Bedrock 請求。"""
    agent = _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN)))
    monkeypatch.setenv("USE_BEDROCK", "false")  # 覆寫 _install_agent 開的旗標

    result = a2.plan_tools(
        "TPE_2026_ACC_001", "Road_Collapse_Accident", SOP2_CLASSIFICATION
    )
    assert result.degraded and agent.calls == 0
    assert "USE_BEDROCK=false" in result.reason


def test_planner_degrades_when_agent_unavailable(monkeypatch):
    monkeypatch.setattr(a2, "_get_a2_agent", lambda: None)
    result = a2.plan_tools("X", "Unknown", {})
    assert result.degraded and result.plan is None


def test_planner_never_raises(monkeypatch):
    """SPEC-O2 §5「永不沉默」：任何失敗都回 PlanResult，不拋例外。"""

    def boom(prompt):
        raise RuntimeError("bedrock exploded")

    _install_agent(monkeypatch, boom)
    result = a2.plan_tools("X", "Unknown", {})
    assert result.degraded and result.plan is None


def test_planner_success_reports_sequence(monkeypatch):
    _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN)))
    result = a2.plan_tools(
        "TPE_2026_ACC_001", "Road_Collapse_Accident", SOP2_CLASSIFICATION
    )
    assert not result.degraded
    assert result.tool_sequence[0] == "RAG_SEARCH"
    assert "CALC_ETE" in result.tool_sequence


def test_planner_does_not_register_tools(monkeypatch):
    """SPEC-O2 §3.1：規劃器不執行工具，因此不得註冊任何 Strands @tool。"""
    captured = {}

    class _FakeStrandsAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import sys
    import types

    fake_mod = types.ModuleType("strands")
    fake_mod.Agent = _FakeStrandsAgent
    monkeypatch.setitem(sys.modules, "strands", fake_mod)

    a2.create_a2_agent()
    assert captured["tools"] == []


# ---------------------------------------------------------------------------
# 靜態分派表（SPEC-O2 §2、§2.1 連動、§2.2 同主責合併）
# ---------------------------------------------------------------------------


def test_static_chain_sop2_contains_full_r_chain():
    from src.orchestrator import static_chain_for_classification

    chain = static_chain_for_classification(SOP2_CLASSIFICATION)
    for tool in (
        ToolName.GRAPH_BUILD,
        ToolName.UPSTREAM_JUDGE,
        ToolName.CANDIDATE_FILTER,
        ToolName.ROUTE_SELECT,
        ToolName.CALC_ETE,
    ):
        assert tool in chain


def test_static_chain_sop5_contains_count_intersections():
    from src.orchestrator import static_chain_for_classification

    chain = static_chain_for_classification(
        {"primary_sop": "SOP-5", "requires_rerouting": False}
    )
    assert ToolName.COUNT_INTERSECTIONS in chain
    assert ToolName.ROUTE_SELECT not in chain


def test_static_chain_appends_translate_when_multilingual():
    from src.orchestrator import static_chain_for_classification

    chain = static_chain_for_classification(SOP2_CLASSIFICATION, multilingual=True)
    assert chain[-1] is ToolName.TRANSLATE


def test_clause_4_auto_chains_clause_3():
    """SPEC-O2 §2.1：批次含 §4 時自動追加 §3。"""
    from src.orchestrator import expand_auto_chained_clauses

    assert expand_auto_chained_clauses(["§1-A", "§4"]) == ["§1-A", "§4", "§3"]
    # 已含 §3 時不重複追加
    assert expand_auto_chained_clauses(["§4", "§3"]) == ["§4", "§3"]


def test_same_owner_tools_merged_once():
    """SPEC-O2 §2.2 同主責合併：重複工具只出現一次。"""
    from src.orchestrator import static_dispatch_chain

    chain = static_dispatch_chain(["§1-A", "§4", "§3"])
    assert len(chain) == len(set(chain))


def test_clause_6_dispatches_nothing():
    """SPEC-O2 §2：§6 只設 flag，不分派任務。"""
    from src.orchestrator import static_dispatch_chain

    chain = static_dispatch_chain(["§6"])
    assert chain == [ToolName.RAG_SEARCH, ToolName.FORMAT_REPORT]


# ---------------------------------------------------------------------------
# SPEC-O2 §6 驗收表
# ---------------------------------------------------------------------------


def test_acceptance_1_rule_batch_never_calls_llm(monkeypatch):
    """#1 規則批次 [§2] 不經 LLM → 規劃器 mock 呼叫次數 = 0。"""
    from src import orchestrator

    agent = _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN)))
    orchestrator.handle_trigger_batch([{"rule": "§2", "segment_id": "RD_TPE_002"}])
    assert agent.calls == 0


def test_acceptance_1b_rule_batch_records_real_tool_sequence(monkeypatch):
    """#1 續：規則批次的 PLAN 紀錄要寫真實工具序列，不是寫死的旗標。"""
    from src import orchestrator
    from src.decision_trace import get_steps

    _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN)))
    result = orchestrator.handle_trigger_batch([{"rule": "§2", "segment_id": "RD_TPE_002"}])

    plan_step = next(s for s in get_steps(result.trace_id) if s.action == "PLAN")
    assert plan_step.output["planned_by"] == "static_dispatch"
    assert "ROUTE_SELECT" in plan_step.output["tools"]
    assert "CALC_ETE" in plan_step.output["tools"]


def test_acceptance_6_clause_merge_and_auto_chain():
    """#6 [§1-A, §4] 合併 + 連動：單一 PLAN 紀錄，clauses 含 §3 且有 auto_chained 註記。"""
    from src import orchestrator
    from src.decision_trace import get_steps

    result = orchestrator.handle_trigger_batch([{"rule": "§1-A"}, {"rule": "§4"}])

    plan_steps = [s for s in get_steps(result.trace_id) if s.action == "PLAN"]
    assert len(plan_steps) == 1
    assert plan_steps[0].input["clauses"] == ["§1-A", "§4", "§3"]
    assert plan_steps[0].input["auto_chained"] == "§3"
    assert result.triggered_by == ["§1-A", "§4"]


def test_trigger_batch_reads_spec_o3_rule_field():
    """SPEC-O3 §2：TriggeredRule 的欄位名是 `rule`，值已含 § 前綴。"""
    from src import orchestrator

    result = orchestrator.handle_trigger_batch([{"rule": "§2"}])
    assert result.triggered_by == ["§2"]


def test_acceptance_2_incident_plan_recorded(monkeypatch):
    """#2 事件注入經 LLM 規劃 → PLAN 紀錄存在且 output 含工具序列。"""
    from src import orchestrator
    from src.decision_trace import get_steps

    _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN)))
    result = asyncio.run(orchestrator.handle_incident(_load_incident()))

    plan_steps = [s for s in get_steps(result.trace_id) if s.action == "PLAN"]
    assert len(plan_steps) == 1
    output = plan_steps[0].output
    assert output["planned_by"] == "a2_llm"
    assert "CALC_ETE" in output["tools"]


def test_acceptance_3_illegal_tool_degrades_to_static(monkeypatch):
    """#3 規劃器回非法工具名 → 計畫作廢、PLAN degraded=true、改走靜態 §2 鏈。"""
    from src import orchestrator
    from src.decision_trace import get_steps

    bad = {"steps": [{"tool": "RAG_SEARCH"}, {"tool": "TOTALLY_MADE_UP"}]}
    _install_agent(monkeypatch, FakeAgent(json.dumps(bad)))
    result = asyncio.run(orchestrator.handle_incident(_load_incident()))

    plan_step = next(s for s in get_steps(result.trace_id) if s.action == "PLAN")
    assert plan_step.input["degraded"] is True
    assert plan_step.output["planned_by"] == "static_dispatch"
    # 降級後仍走完整 §2 鏈，黃金值不受影響
    assert "ROUTE_SELECT" in plan_step.output["tools"]
    assert result.routes.primary.segment_id == "RD_TPE_004"


def test_acceptance_4_missing_calc_ete_intercepted(monkeypatch):
    """#4 規劃器漏 CALC_ETE（§2 事件）→ 必要步驟檢查攔截 → 降級靜態鏈。"""
    from src import orchestrator
    from src.decision_trace import get_steps

    steps = [s for s in FULL_SOP2_PLAN["steps"] if s["tool"] != "CALC_ETE"]
    _install_agent(monkeypatch, FakeAgent(json.dumps({"steps": steps})))
    result = asyncio.run(orchestrator.handle_incident(_load_incident()))

    plan_step = next(s for s in get_steps(result.trace_id) if s.action == "PLAN")
    assert plan_step.input["degraded"] is True
    assert "CALC_ETE" in plan_step.input["reason"]
    # 降級後 ETE 仍算得出來（黃金值 90 分）
    assert result.ete.minutes == 90


def test_acceptance_11_golden_values_with_llm_plan(monkeypatch):
    """#11 黃金值回歸：LLM 規劃成功時，事實欄位仍由決定性模組產出。"""
    from src import orchestrator

    _install_agent(monkeypatch, FakeAgent(json.dumps(FULL_SOP2_PLAN)))
    result = asyncio.run(orchestrator.handle_incident(_load_incident()))

    assert result.routes.primary.segment_id == "RD_TPE_004"
    assert result.routes.secondary.segment_id == "RD_TPE_005"
    excluded = {e.segment_id: e.reason_code for e in result.routes.excluded}
    assert excluded["RD_TPE_006"] == "NOT_DIRECTLY_INTERSECTING"
    assert excluded["RD_TPE_008"] == "CAPACITY_INSUFFICIENT"
    assert result.ete.minutes == 90
    assert result.ete.recovery_at == "2026-05-20 23:40"
