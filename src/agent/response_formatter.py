"""解析 Agent 回覆、結合 tool 呼叫結果，組成 W1Response。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第七、八節。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.system_prompt import DEFAULT_QUESTIONS


@dataclass
class W1Response:
    """W1 回傳給 API 的最終格式（design.md 第七節）。"""

    intent_type: str
    """"chitchat" | "sop_query" | "whatif_simulation"。"""
    summary: str
    triggered_sops: list[dict]
    judgment_basis: str | None
    expected_actions: list[str]
    route_impact: dict | None
    ete: dict | None
    current_data: dict | None
    suggested_questions: list[str]
    source_mode: str
    """"full"（A2可用）| "degraded"（A2不可用，僅K3）。"""
    tools_called: list[str]


def format_response(raw_response, context) -> W1Response:
    """解析策略（design.md 第八節）：
    - 從 Agent trace 取得 tool call 結果，依呼叫了哪些 tool 判定 intent_type
    - query_sop 結果填入 triggered_sops；simulate_scenario 結果填入 ete/route_impact/expected_actions
    - Agent 最終文字回覆作為 summary；延伸問題從回覆中解析，解析不到用 DEFAULT_QUESTIONS

    TODO(Kiro): 依 design.md 第八節完整實作。
    """
    raise NotImplementedError("見 W1-whatif-agent/design.md 第八節")
