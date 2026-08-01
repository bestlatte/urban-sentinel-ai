"""解析 Agent 回覆、結合 tool 呼叫結果，組成 W1Response。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第七、八節。

[2026-08-01 重寫 tool 結果抽取——原實作對不上 Strands 的實際資料結構]
--------------------------------------------------------------------
原本的 `_extract_tool_results()` 依序嘗試 `raw_response.messages`、
`raw_response.tool_results`。實測 Strands 的 `AgentResult` 欄位是：

    ['stop_reason', 'message', 'metrics', 'state', 'interrupts',
     'structured_output', 'checkpoint']

三個分支全部落空，函式**永遠回傳空 dict**。連鎖後果是整條結構化欄位鏈死掉：
`tools_called=[]` → `intent_type` 永遠 `"chitchat"` → `triggered_sops` 永遠空 →
`ete`／`route_impact`／`current_data` 永遠 `None` → `source_mode` 永遠 `"degraded"`。
也就是 `whatif_engine` 重算出來的東西一個都沒送到前端。

正確來源是 **`agent.messages`**（Agent 實例上的對話歷史，不是 AgentResult），
實測結構：

    [{"role": "user",      "content": [{"text": ...}]},
     {"role": "assistant", "content": [{"toolUse": {"toolUseId", "name", "input"}}]},
     {"role": "user",      "content": [{"toolResult": {"toolUseId", "status",
                                                       "content": [{"text": "<JSON字串>"}]}}]},
     ...]

要點三個：工具結果在 **user** 訊息裡（不是 assistant）、以 `toolUseId` 跟呼叫配對、
`content[].text` 是**被 json.dumps 過的字串**必須再 parse 一次。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.agent.system_prompt import DEFAULT_QUESTIONS

logger = logging.getLogger(__name__)


@dataclass
class W1Response:
    """W1 回傳給 API 的最終格式（design.md 第七節）。"""

    intent_type: str
    """"chitchat" | "sop_query" | "whatif_simulation" | "scenario_report"。"""
    summary: str
    triggered_sops: list[dict] = field(default_factory=list)
    judgment_basis: str | None = None
    expected_actions: list[str] = field(default_factory=list)
    route_impact: dict | None = None
    ete: dict | None = None
    current_data: dict | None = None
    suggested_questions: list[str] = field(default_factory=list)
    source_mode: str = "degraded"
    """"full"（決策模組可用）| "degraded"（LLM 或決策模組不可用，僅 K3 本機 SOP）。"""
    tools_called: list[str] = field(default_factory=list)
    scenario_report: str | None = None
    """方案B：假設情境交控建議書全文。只有使用者明確要求出報告時才有值。"""
    differences_from_base: list[dict] = field(default_factory=list)
    """情境跟正式決策的差異（`whatif_engine.diff_from_base()` 的輸出）。"""
    judgment_steps: list[dict] = field(default_factory=list)
    """結構化推理鏈（`whatif_engine.build_judgment_steps()` 的輸出）。

    前端 `renderReasoningChain()` 用這個畫「假設 → 命中條款 → 路線 → ETE」的
    圖，`judgment_basis` 那份純文字則留給不支援結構化渲染的呼叫端。
    """
    hypothetical_incident: dict | None = None
    """假想事故的描述（哪條路、評估時刻、使用者有沒有指定嚴重度）。

    [2026-08-01] 使用者說「如果市民大道四段封閉」時，系統會合成一起假想事故，
    否則這個假設對規則引擎完全空轉——SOP-1 只看飽和度、SOP-2 需要 Incident
    物件，改 `lane_status` 一條規則都不會反應。見 `whatif_engine.synthesize_incident()`。
    """
    severity_options: list[dict] = field(default_factory=list)
    """嚴重度並列比較（Critical / High / Medium 各自的 ETE、改道、後續風險）。

    只有在使用者**沒有**指明嚴重度時才有值。ETE 在三者之間差到 40 分鐘
    （SOP-7 base_clearance 60/40/20），猜一個等於給出他沒同意過的調度依據。
    """
    trace_id: str | None = None
    """本次回答所依據的決策週期 ID（使用者正在查看的那一個）。"""
    projected_risks: dict | None = None
    """後續風險推演（`risk_projection.projection_to_dict()`）。

    對話裡問「這樣改道會有什麼問題」時，答案跟 Dashboard 建議書上那張圖
    必然一致——兩邊來自同一次推演。
    """
    trace_steps: list[dict] = field(default_factory=list)
    """決策軌跡步驟（`decision_trace.get_trace_view()` 的 `steps`）。

    [2026-08-01 新增] 決策軌跡原本只有 M4B 生成層讀得到，沒有任何路徑送到前端
    ——所以 chatbot 回答「這個決策怎麼來的」時只有一段散文，看不到實際步驟
    （誰做的、用什麼工具、依據哪條 SOP、排除了什麼、為什麼）。
    """


@dataclass
class ToolInvocation:
    """一次工具呼叫的完整紀錄（呼叫參數 + 回傳結果）。

    保留 `input` 是必要的：`whatif_agent._extract_new_assumptions()` 要靠
    `simulate_scenario` 的 input 才知道使用者這輪提了什麼假設，好交給 W2 累積。
    只存 output 的話多輪對話的假設累積永遠做不到（那正是原本的狀況——該函式
    直接 `return None`，註解寫「Agent 的 tool call input 不一定能從 response
    中逆推」，其實從 `agent.messages` 逆推得到）。
    """

    name: str
    tool_use_id: str
    input: dict
    output: Any = None
    status: str = "success"

    @property
    def ok(self) -> bool:
        """工具本身回成功，且結果沒有被業務層標記為降級。"""
        if self.status != "success":
            return False
        if isinstance(self.output, dict):
            if self.output.get("fallback") or self.output.get("status") == "unavailable":
                return False
        return True


def _parse_tool_result_content(content: list) -> Any:
    """把 toolResult 的 content 陣列還原成 Python 值。

    Strands 把工具回傳值 `json.dumps` 後塞進 `{"text": ...}`，所以要 parse 回來。
    偶爾也會出現 `{"json": ...}` 直接帶結構（不同 model provider 行為不同），
    兩種都收。parse 失敗就保留原字串——寧可給呼叫端一個字串，也不要吞掉內容。
    """
    if not content:
        return None

    for block in content:
        if not isinstance(block, dict):
            continue
        if "json" in block:
            return block["json"]
        if "text" in block:
            text = block["text"]
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
    return None


def extract_tool_invocations(messages: list) -> list[ToolInvocation]:
    """從 `agent.messages` 抽出所有工具呼叫，依發生順序回傳。

    同一個工具被呼叫多次（Agent 換個問法重查很常見）會回傳多筆，不去重——
    去重是呼叫端的語意決策，抽取層不該替它決定要留第一次還是最後一次。
    """
    if not messages:
        return []

    invocations: list[ToolInvocation] = []
    by_id: dict[str, ToolInvocation] = {}

    for message in messages:
        if not isinstance(message, dict):
            continue
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue

            if "toolUse" in block:
                use = block["toolUse"] or {}
                raw_input = use.get("input")
                inv = ToolInvocation(
                    name=use.get("name", ""),
                    tool_use_id=use.get("toolUseId", ""),
                    input=raw_input if isinstance(raw_input, dict) else {},
                )
                invocations.append(inv)
                if inv.tool_use_id:
                    by_id[inv.tool_use_id] = inv

            elif "toolResult" in block:
                result = block["toolResult"] or {}
                inv = by_id.get(result.get("toolUseId", ""))
                if inv is None:
                    # 沒配對到呼叫端（理論上不會發生，但對話歷史被截斷時可能）。
                    # 靜靜略過會讓「工具明明跑了卻沒結果」變成無聲失敗，記一筆。
                    logger.debug("toolResult 找不到對應的 toolUse: %s", result.get("toolUseId"))
                    continue
                inv.status = result.get("status", "success")
                inv.output = _parse_tool_result_content(result.get("content") or [])

    return invocations


def _extract_tool_results(raw_response) -> dict[str, dict]:
    """舊介面：`{tool_name: result}`。保留給直接傳 dict 的測試與呼叫端。

    新程式請改用 `extract_tool_invocations(agent.messages)`——這個介面用工具名
    當 key，同一個工具呼叫兩次會互相覆蓋，而且拿不到呼叫參數。
    """
    if isinstance(raw_response, dict):
        return raw_response.get("tool_results", {})
    return {}


def _response_text(raw_response) -> str:
    """取 Agent 的最終文字回覆。

    優先讀 `AgentResult.message["content"][*]["text"]`（實測的正確路徑）。
    """
    if isinstance(raw_response, str):
        return raw_response

    message = getattr(raw_response, "message", None)
    if isinstance(message, dict):
        texts = [
            block["text"]
            for block in (message.get("content") or [])
            if isinstance(block, dict) and "text" in block
        ]
        if texts:
            return "\n".join(texts)

    if hasattr(raw_response, "text"):
        return raw_response.text
    if isinstance(raw_response, dict) and "text" in raw_response:
        return raw_response["text"]

    return str(raw_response)


def _extract_summary(text: str) -> str:
    """從 Agent 回覆文字中提取摘要（移除延伸問題區塊）。"""
    for marker in ("延伸問題", "建議問題", "您可能還想了解", "你可能還想問"):
        idx = text.find(marker)
        if idx > 0:
            # 截在標題所在行的開頭，避免留下 "## " 或 "**" 之類的殘缺標記
            line_start = text.rfind("\n", 0, idx)
            cut = line_start if line_start > 0 else idx
            return text[:cut].strip().rstrip("#*- \n")
    return text.strip()


def _extract_suggested_questions(text: str) -> list[str]:
    """從 Agent 回覆文字中解析延伸問題（`prompts/advisor.txt` 要求生成 3 個）。

    解析不到用 DEFAULT_QUESTIONS。
    """
    start_idx = -1
    for marker in ("延伸問題", "建議問題", "您可能還想了解", "你可能還想問"):
        idx = text.find(marker)
        if idx >= 0:
            start_idx = idx
            break

    if start_idx < 0:
        return list(DEFAULT_QUESTIONS)

    remaining = text[start_idx:]
    questions = re.findall(r"(?:^|\n)\s*(?:\d+[.、）)]|[-•*])\s*(.+)", remaining)
    # 去掉 markdown 粗體標記與尾端空白；空字串丟掉
    cleaned = [q.strip().strip("*").strip() for q in questions]
    cleaned = [q for q in cleaned if q]

    if cleaned:
        return cleaned[:3]
    return list(DEFAULT_QUESTIONS)


def _merge_sop_sections(invocations: list[ToolInvocation]) -> list[dict]:
    """合併所有 `query_sop` 的命中條款，依 section_number 去重取最高分。

    Agent 查不到時常會換個問法再查一次（實測行為），只取最後一次會把第一次
    查到的條款丟掉。合併並依相關度排序才是使用者要的。
    """
    best: dict[int, dict] = {}
    for inv in invocations:
        if inv.name != "query_sop" or not isinstance(inv.output, dict):
            continue
        for section in inv.output.get("sections") or []:
            if not isinstance(section, dict):
                continue
            num = section.get("section_number")
            if num is None:
                continue
            prev = best.get(num)
            if prev is None or section.get("relevance_score", 0) > prev.get("relevance_score", 0):
                best[num] = section

    return sorted(
        best.values(),
        key=lambda s: (-s.get("relevance_score", 0), s.get("section_number", 0)),
    )


def _flatten_route_impact(route_plan: dict | None) -> dict | None:
    """把 `RoutePlan` dump 壓成前端能直接顯示的字串結構。

    [2026-08-01 修正：畫面上顯示 `[object Object]`]
    ----------------------------------------------
    原本 `route_impact` 直接塞整個 `RoutePlan.model_dump()`，但前端
    `chat-render.js::renderDecisionCard()` 做的是
    `escapeHtml(data.route_impact.primary)` ——它期待的是**路段名字串**，
    拿到的卻是 `{"segment_id": ..., "name": ..., "saturation_score": ...}`
    這個物件，JS 轉字串就變成 `[object Object]`。

    卡片上「路網影響」那一列從來沒有顯示過正確內容。完整的 RoutePlan 現在由
    `judgment_steps` 的 routes 階段負責呈現，這裡只給精簡標籤用的名字。
    """
    if not isinstance(route_plan, dict):
        return None

    def _name(candidate) -> str | None:
        if isinstance(candidate, dict):
            return candidate.get("name") or candidate.get("segment_id")
        return None

    flattened: dict = {}
    primary = _name(route_plan.get("primary"))
    secondary = _name(route_plan.get("secondary"))
    if primary:
        flattened["primary"] = primary
    if secondary:
        flattened["secondary"] = secondary

    blocked = [
        n for n in (_name(exc) for exc in route_plan.get("excluded") or []) if n
    ]
    if blocked:
        flattened["blocked"] = blocked

    return flattened or None


def format_response(raw_response, context, messages: list | None = None) -> W1Response:
    """解析策略（design.md 第八節）：

    - 從 `agent.messages` 取得工具呼叫與結果
    - 依呼叫了哪些 tool 判定 intent_type
    - query_sop 結果合併後填入 triggered_sops
    - simulate_scenario 結果填入 ete/route_impact/expected_actions/judgment_basis
    - Agent 最終文字回覆作為 summary
    - 延伸問題從回覆中解析，解析不到用 DEFAULT_QUESTIONS

    Args:
        raw_response: Strands `AgentResult`、字串，或 `{"text", "tool_results"}` dict
        context: `W1Context`，保留供未來擴充
        messages: `agent.messages`。**這是工具結果的正確來源**，沒傳的話只能
            退回舊的 dict 介面（測試用），結構化欄位會是空的。
    """
    response_text = _response_text(raw_response)

    invocations = extract_tool_invocations(messages or [])

    # 舊 dict 介面相容：`{"tool_results": {"query_sop": {...}}}`
    if not invocations:
        for name, output in _extract_tool_results(raw_response).items():
            invocations.append(ToolInvocation(name=name, tool_use_id="", input={}, output=output))

    tools_called: list[str] = []
    for inv in invocations:
        if inv.name and inv.name not in tools_called:
            tools_called.append(inv.name)

    if not tools_called:
        intent_type = "chitchat"
    elif "simulate_scenario" in tools_called:
        intent_type = "whatif_simulation"
    else:
        intent_type = "sop_query"

    triggered_sops = _merge_sop_sections(invocations)

    # 取最後一次成功的模擬；全部失敗時取最後一次（保留錯誤訊息供降級判斷）
    sim_calls = [i for i in invocations if i.name == "simulate_scenario"]
    successful = [i for i in sim_calls if i.ok]
    sim = successful[-1] if successful else (sim_calls[-1] if sim_calls else None)
    simulation = sim.output if (sim and isinstance(sim.output, dict)) else {}

    # source_mode 語意：這次回答有沒有走完整管線。
    #   模擬成功        → full
    #   模擬失敗/降級   → degraded
    #   沒有模擬需求    → full（純 SOP 問答本來就不需要決策模組，不算降級；
    #                    真正的降級路徑是 whatif_agent._degraded_response()，
    #                    那裡會明確寫 "degraded"）
    source_mode = "full" if (sim is None or sim.ok) else "degraded"

    return W1Response(
        intent_type=intent_type,
        summary=_extract_summary(response_text),
        triggered_sops=triggered_sops,
        judgment_basis=simulation.get("judgment_basis"),
        judgment_steps=simulation.get("judgment_steps") or [],
        expected_actions=simulation.get("actions", []),
        route_impact=(
            simulation.get("route_impact")
            or _flatten_route_impact(simulation.get("route_plan"))
        ),
        ete=simulation.get("ete"),
        current_data=simulation.get("current_data_snapshot"),
        suggested_questions=_extract_suggested_questions(response_text),
        source_mode=source_mode,
        tools_called=tools_called,
        # [2026-08-01] 假想事故三件套。使用者問「如果某某路封閉」時，
        # `whatif_engine` 會合成一起假想事故讓整條鏈跑起來（見 synthesize_incident），
        # 這三個欄位把結果帶到前端：假設本身、嚴重度比較表、二階風險推演。
        hypothetical_incident=simulation.get("hypothetical_incident"),
        severity_options=simulation.get("severity_options") or [],
        projected_risks=simulation.get("risk_projection"),
    )
