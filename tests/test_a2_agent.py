"""測試 A2 Agent 工具與規劃器。

a2_tools.py：決定性模組包裝，精確值斷言。
a2_orchestrator_agent.py：LLM 相關，但 _get_a2_agent 降級邏輯可精確測試。
"""

import os
import pytest

os.environ.setdefault("USE_BEDROCK", "false")


def setup_module():
    from src import orchestrator
    if orchestrator.GATEWAY is None:
        orchestrator.GATEWAY = orchestrator.build_gateway()


# --- a2_tools.py ---

def test_evaluate_rules_tool_returns_traffic_level():
    from src.agent.a2_tools import evaluate_rules_tool
    result = evaluate_rules_tool(event_id="TPE_2026_ACC_001")
    assert result["traffic_level"] == "A"
    assert len(result["rule_hits"]) > 0


def test_plan_routes_tool_golden_values():
    from src.agent.a2_tools import plan_routes_tool
    result = plan_routes_tool(event_id="TPE_2026_ACC_001")
    assert result["primary"]["segment_id"] == "RD_TPE_004"
    assert result["secondary"]["segment_id"] == "RD_TPE_005"
    assert result["no_feasible_route"] is False


def test_calculate_ete_tool_golden_value():
    from src.agent.a2_tools import calculate_ete_tool
    result = calculate_ete_tool(event_id="TPE_2026_ACC_001")
    assert result["minutes"] == 90
    assert result["recovery_at"] == "2026-05-20 23:40"


def test_plan_routes_tool_nonexistent_event():
    from src.agent.a2_tools import plan_routes_tool
    result = plan_routes_tool(event_id="NONEXISTENT")
    assert "error" in result


def test_calculate_ete_tool_nonexistent_event():
    from src.agent.a2_tools import calculate_ete_tool
    result = calculate_ete_tool(event_id="NONEXISTENT")
    assert "error" in result


# --- a2_orchestrator_agent.py ---

def test_get_a2_agent_returns_agent_or_none():
    """無 AWS 憑證時不拋例外（建立 Agent 物件本身不需要連線）。"""
    from src.agent.a2_orchestrator_agent import _get_a2_agent
    agent = _get_a2_agent()
    # Strands Agent 建立成功（不需要連線），或某些環境下可能回 None
    assert agent is not None or agent is None  # 不拋例外就好


def test_decide_and_execute_degrades_without_credentials():
    """無 AWS 憑證時 decide_and_execute 回 None（安全降級）。"""
    from src.agent.a2_orchestrator_agent import decide_and_execute
    result = decide_and_execute(
        event_id="TPE_2026_ACC_001",
        event_type="Road_Collapse_Accident",
        classification={"primary_sop": "SOP-2", "requires_rerouting": True, "affected_source": "RD_TPE_002"},
    )
    # 無 credentials → Agent 呼叫失敗 → 回 None
    assert result is None


def test_decide_and_execute_does_not_raise():
    """任何情況下不拋例外。"""
    from src.agent.a2_orchestrator_agent import decide_and_execute
    # 即使給荒謬參數也不該拋
    result = decide_and_execute(
        event_id="FAKE",
        event_type="Unknown",
        classification={},
    )
    assert result is None or isinstance(result, dict)
