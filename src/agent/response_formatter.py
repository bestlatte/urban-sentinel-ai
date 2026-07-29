"""解析 Agent 回覆、結合 tool 呼叫結果，組成 W1Response。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第七、八節。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.agent.system_prompt import DEFAULT_QUESTIONS


@dataclass
class W1Response:
    """W1 回傳給 API 的最終格式（design.md 第七節）。"""

    intent_type: str
    """"chitchat" | "sop_query" | "whatif_simulation"。"""
    summary: str
    triggered_sops: list[dict] = field(default_factory=list)
    judgment_basis: str | None = None
    expected_actions: list[str] = field(default_factory=list)
    route_impact: dict | None = None
    ete: dict | None = None
    current_data: dict | None = None
    suggested_questions: list[str] = field(default_factory=list)
    source_mode: str = "degraded"
    """"full"（A2可用）| "degraded"（A2不可用，僅K3）。"""
    tools_called: list[str] = field(default_factory=list)


def _extract_tool_results(raw_response) -> dict[str, dict]:
    """從 Strands Agent 的 response 物件中提取 tool call 結果。

    Strands Agent 的回傳值帶有 tool call 紀錄。目前支援兩種情境：
    - raw_response 是 dict 且有 "tool_results" key（手動傳入）
    - raw_response 是 Strands Agent 的回傳物件（有 .messages 或類似屬性）
    """
    if isinstance(raw_response, dict):
        return raw_response.get("tool_results", {})

    # Strands Agent response — 嘗試從 messages/tool_use 提取
    tool_results: dict[str, dict] = {}
    if hasattr(raw_response, "messages"):
        for msg in raw_response.messages:
            if hasattr(msg, "tool_use"):
                for use in msg.tool_use:
                    tool_results[use.name] = use.result if hasattr(use, "result") else {}
    elif hasattr(raw_response, "tool_results"):
        return raw_response.tool_results

    return tool_results


def _extract_summary(text: str) -> str:
    """從 Agent 回覆文字中提取摘要（移除延伸問題區塊）。"""
    # 嘗試在「延伸問題」或「建議問題」之前截斷
    for marker in ("延伸問題", "建議問題", "您可能還想了解", "你可能還想問"):
        idx = text.find(marker)
        if idx > 0:
            return text[:idx].strip()
    return text.strip()


def _extract_suggested_questions(text: str) -> list[str]:
    """從 Agent 回覆文字中解析延伸問題（Agent 被 prompt 要求生成 3 個）。

    嘗試找編號列表格式（1. xxx 2. xxx 3. xxx）或 - xxx 格式。
    解析不到用 DEFAULT_QUESTIONS。
    """
    # 找 "延伸問題" 之後的內容
    start_idx = -1
    for marker in ("延伸問題", "建議問題", "您可能還想了解", "你可能還想問"):
        idx = text.find(marker)
        if idx >= 0:
            start_idx = idx
            break

    if start_idx < 0:
        return list(DEFAULT_QUESTIONS)

    remaining = text[start_idx:]
    # 嘗試匹配 "1. xxx" 或 "- xxx" 格式
    questions = re.findall(r"(?:^|\n)\s*(?:\d+[.、）]|[-•])\s*(.+)", remaining)
    questions = [q.strip() for q in questions if q.strip()]

    if len(questions) >= 1:
        return questions[:3]
    return list(DEFAULT_QUESTIONS)


def format_response(raw_response, context) -> W1Response:
    """解析策略（design.md 第八節）：

    - 從 Agent trace 取得 tool call 結果
    - 依呼叫了哪些 tool 判定 intent_type
    - query_sop 結果填入 triggered_sops
    - simulate_scenario 結果填入 ete/route_impact/expected_actions
    - Agent 最終文字回覆作為 summary
    - 延伸問題從回覆中解析，解析不到用 DEFAULT_QUESTIONS
    """
    # 取得文字回覆
    if isinstance(raw_response, str):
        response_text = raw_response
    elif hasattr(raw_response, "text"):
        response_text = raw_response.text
    elif isinstance(raw_response, dict) and "text" in raw_response:
        response_text = raw_response["text"]
    else:
        response_text = str(raw_response)

    # 從 Agent trace 取得 tool call results
    tool_results = _extract_tool_results(raw_response)

    # 判斷意圖
    tools_called = list(tool_results.keys())
    if not tools_called:
        intent_type = "chitchat"
    elif "simulate_scenario" in tools_called:
        intent_type = "whatif_simulation"
    else:
        intent_type = "sop_query"

    # 從 tool results 填入結構化欄位
    triggered_sops: list[dict] = []
    if "query_sop" in tool_results:
        sop_result = tool_results["query_sop"]
        if isinstance(sop_result, dict):
            triggered_sops = sop_result.get("sections", [])

    simulation = tool_results.get("simulate_scenario", {})
    if not isinstance(simulation, dict):
        simulation = {}

    # 判斷 source_mode
    is_fallback = simulation.get("fallback", False) or simulation.get("status") == "unavailable"
    source_mode = "degraded" if (not simulation or is_fallback) else "full"

    # 解析延伸問題
    suggested_questions = _extract_suggested_questions(response_text)

    return W1Response(
        intent_type=intent_type,
        summary=_extract_summary(response_text),
        triggered_sops=triggered_sops,
        judgment_basis=simulation.get("judgment_basis"),
        expected_actions=simulation.get("actions", []),
        route_impact=simulation.get("route_impact") or simulation.get("route_plan"),
        ete=simulation.get("ete"),
        current_data=simulation.get("current_data_snapshot"),
        suggested_questions=suggested_questions,
        source_mode=source_mode,
        tools_called=tools_called,
    )
