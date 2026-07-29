"""W1 主邏輯：建立 Agent 實例、process_whatif()、process_whatif_request()。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md`
（已修正版第五、六、十節）。

**進場方式（重要，不要照抄該資料夾 tasks.md 舊版寫法）**：
`POST /api/what-if` 收到請求 → `orchestrator.handle_user_query()`（見
`m4-explanation-chain-and-orchestrator/SPEC-O3` §4）判斷是前瞻假設問題 →
呼叫本檔的 `process_whatif_request()` → 同步回傳完整結果。不是 W1 自己接
WebSocket 訊息、自己決定要不要處理。
"""

from __future__ import annotations

import logging
import os

from src.agent.response_formatter import W1Response, format_response
from src.agent.system_prompt import SYSTEM_PROMPT, DEFAULT_QUESTIONS
from src.agent.tools import query_sop, simulate_scenario
from src.session.models import W1Context

logger = logging.getLogger(__name__)


def create_whatif_agent():
    """建立 W1 Agent 實例。model ID 從環境變數讀取，不得硬編碼。"""
    from strands import Agent

    return Agent(
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"),
        tools=[query_sop, simulate_scenario],
        system_prompt=SYSTEM_PROMPT,
    )


WHATIF_AGENT = None
"""延遲初始化：首次呼叫 process_whatif 時才建立，避免 import 時就需要 AWS 連線。"""


def _get_agent():
    """取得或建立全域 Agent 實例。"""
    global WHATIF_AGENT
    if WHATIF_AGENT is None:
        try:
            WHATIF_AGENT = create_whatif_agent()
        except Exception as e:
            logger.warning(f"無法建立 Strands Agent: {e}，將使用降級模式")
            return None
    return WHATIF_AGENT


def _build_prompt(context: W1Context) -> str:
    """把 W1Context（history + assumptions + new_message）組成一段 prompt。"""
    parts = []

    # 對話歷史
    if context.history:
        parts.append("=== 對話歷史 ===")
        for turn in context.history:
            parts.append(f"使用者：{turn.user_message}")
            parts.append(f"顧問：{turn.ai_response}")
        parts.append("")

    # 累積假設
    if context.accumulated_assumptions:
        parts.append("=== 目前累積的假設條件 ===")
        for key, value in context.accumulated_assumptions.items():
            parts.append(f"- {key} = {value}")
        parts.append("")

    # 本次訊息
    parts.append(f"使用者新問題：{context.new_message}")

    return "\n".join(parts)


def process_whatif(context: W1Context) -> W1Response:
    """呼叫 WHATIF_AGENT(prompt) → format_response()。LLM 呼叫失敗時回傳
    錯誤用的 W1Response，不得讓例外往上拋（永不沉默原則）。
    """
    agent = _get_agent()
    prompt = _build_prompt(context)

    if agent is None:
        # Agent 建立失敗，降級：只用 query_sop
        return _degraded_response(context)

    try:
        raw_response = agent(prompt)
        return format_response(raw_response, context)
    except Exception as e:
        logger.exception(f"W1 Agent 呼叫失敗: {e}")
        return _degraded_response(context)


def _degraded_response(context: W1Context) -> W1Response:
    """LLM 不可用時的降級回覆：只用 query_sop 做本機 SOP 查詢。"""
    try:
        sop_result = query_sop(question=context.new_message)
        triggered_sops = sop_result.get("sections", []) if isinstance(sop_result, dict) else []
        summary = "系統暫時忙碌，以下為基於 SOP 條款的參考資訊。"
        if triggered_sops:
            for s in triggered_sops:
                summary += f"\n\n【SOP-{s['section_number']}】{s['title']}\n{s['content'][:100]}..."
    except Exception:
        triggered_sops = []
        summary = "系統暫時忙碌，請稍後再試。"

    return W1Response(
        intent_type="sop_query",
        summary=summary,
        triggered_sops=triggered_sops,
        suggested_questions=list(DEFAULT_QUESTIONS),
        source_mode="degraded",
        tools_called=["query_sop"] if triggered_sops else [],
    )


def _extract_new_assumptions(response: W1Response) -> dict[str, float | int | str] | None:
    """從模擬結果中提取新假設（供 W2 record_response 更新 session.assumptions）。

    如果 simulate_scenario 被呼叫，其 input assumptions 就是新假設。
    目前簡化：暫不提取（Agent 的 tool call input 不一定能從 response 中逆推），
    留待 Phase 8 整合時有完整 Agent trace 再補。
    """
    return None


def process_whatif_request(session_id: str, content: str, ws_broadcaster=None) -> W1Response:
    """由 orchestrator.handle_user_query() 呼叫的對外入口。

    流程：W2.handle_message() 組上下文 → （可選）推播 loading 進度
    → process_whatif() → W2.record_response() → 回傳給呼叫端。
    """
    from src.session.session_manager import handle_message, record_response
    from src.agent.loading import broadcast_loading_start_sync, broadcast_loading_complete_sync

    # 1. W2 組上下文
    context = handle_message(session_id, content)

    # 2. 推播 loading 開始（額外通知，不影響主流程）
    broadcast_loading_start_sync(ws_broadcaster, correlation_id=session_id)

    # 3. W1 處理
    response = process_whatif(context)

    # 4. 推播 loading 完成
    broadcast_loading_complete_sync(ws_broadcaster, correlation_id=session_id)

    # 5. W2 記錄回覆
    record_response(
        session_id=session_id,
        user_message=content,
        ai_response=response.summary,
        triggered_sops=[s.get("section_number", 0) for s in response.triggered_sops] if response.triggered_sops else None,
        new_assumptions=_extract_new_assumptions(response),
    )

    return response
