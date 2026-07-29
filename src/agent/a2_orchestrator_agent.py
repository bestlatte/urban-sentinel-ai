"""A2 LLM 規劃器：事件注入時由 LLM 決定呼叫哪些工具、什麼順序。

SPEC-O2 §3：事件注入流程用 A2 LLM 規劃器（折衷制），失敗時降級為靜態分派表。
system prompt 的工具呼叫條件跟 orchestrator.classify_incident() 一致。
"""

from __future__ import annotations

import logging
import os

from src.agent.a2_tools import calculate_ete_tool, evaluate_rules_tool, plan_routes_tool

logger = logging.getLogger(__name__)


def _build_a2_system_prompt() -> str:
    """A2 規劃器的 system prompt。工具呼叫條件對齊 classify_incident()。"""
    return """你是交通指揮系統的 A2 編排規劃器。你的任務是決定要呼叫哪些工具來處理一筆交通事件。

可用工具：
- evaluate_rules_tool：評估全路網規則，取得交通等級與命中 SOP
- plan_routes_tool：規劃替代路線（僅車禍/路障類事件需要）
- calculate_ete_tool：計算預計恢復時間（所有事件都需要）

規則：
1. 所有事件都必須呼叫 evaluate_rules_tool 和 calculate_ete_tool。
2. 只有 Road_Collapse_Accident 類型（對應 SOP-2）才需要呼叫 plan_routes_tool。
3. Crowd_Surge_Injury（SOP-3）和 Power_Failure（SOP-5）不需要路網重規劃。
4. 先呼叫 evaluate_rules_tool，再根據結果決定是否需要 plan_routes_tool，最後呼叫 calculate_ete_tool。
5. 產出 JSON 格式的工具呼叫序列，不自行計算數值。
"""


_A2_AGENT = None


def create_a2_agent():
    """建立 A2 Agent 實例。"""
    from strands import Agent

    return Agent(
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
        tools=[evaluate_rules_tool, plan_routes_tool, calculate_ete_tool],
        system_prompt=_build_a2_system_prompt(),
    )


def _get_a2_agent():
    """取得或建立 A2 Agent。無 AWS 憑證時回傳 None（比照 whatif_agent 慣例）。"""
    global _A2_AGENT
    if _A2_AGENT is None:
        try:
            _A2_AGENT = create_a2_agent()
        except Exception as e:
            logger.warning(f"無法建立 A2 Agent: {e}，將使用靜態分派降級")
            return None
    return _A2_AGENT


def decide_and_execute(event_id: str, event_type: str, classification: dict) -> dict | None:
    """讓 A2 LLM 規劃器決定工具呼叫順序並執行。

    回傳結構化結果 dict，或 None（表示降級為靜態分派）。
    任何失敗都回傳 None，不拋例外（呼叫端 orchestrator 據此走降級路徑）。

    Args:
        event_id: 事件 ID
        event_type: 事件類型（如 Road_Collapse_Accident）
        classification: classify_incident() 的回傳值
    """
    agent = _get_a2_agent()
    if agent is None:
        return None

    prompt = (
        f"事件 ID: {event_id}\n"
        f"事件類型: {event_type}\n"
        f"分類結果: 主因 SOP={classification.get('primary_sop')}, "
        f"需要路網重規劃={classification.get('requires_rerouting')}\n"
        f"請依規則決定要呼叫哪些工具並執行。"
    )

    try:
        raw_response = agent(prompt)
        # 從 Agent 回傳中提取結構化結果
        return _extract_results(raw_response, event_id)
    except Exception as e:
        logger.warning(f"A2 Agent 呼叫失敗: {e}，降級為靜態分派")
        return None


def _extract_results(raw_response, event_id: str) -> dict:
    """從 Agent response 中提取工具呼叫結果。"""
    results = {
        "planned_by": "a2_llm",
        "event_id": event_id,
        "sensing": None,
        "route_plan": None,
        "ete": None,
    }

    # 嘗試從 response 的 tool results 取值
    if hasattr(raw_response, "messages"):
        for msg in getattr(raw_response, "messages", []):
            if hasattr(msg, "tool_use"):
                for use in msg.tool_use:
                    if hasattr(use, "name") and hasattr(use, "result"):
                        if "evaluate_rules" in use.name:
                            results["sensing"] = use.result
                        elif "plan_routes" in use.name:
                            results["route_plan"] = use.result
                        elif "calculate_ete" in use.name:
                            results["ete"] = use.result

    return results
