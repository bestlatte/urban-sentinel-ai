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

import os

from src.agent.response_formatter import W1Response, format_response
from src.agent.system_prompt import SYSTEM_PROMPT
from src.agent.tools import query_sop, simulate_scenario
from src.session.models import W1Context


def create_whatif_agent():
    """建立 W1 Agent 實例。model ID 從環境變數讀取，不得硬編碼
    （design.md 已修正：原本硬編碼 model 字串跟自己的 tasks.md 互相矛盾）。
    """
    from strands import Agent

    return Agent(
        model=os.environ["BEDROCK_MODEL_ID"],
        tools=[query_sop, simulate_scenario],
        system_prompt=SYSTEM_PROMPT,
    )


WHATIF_AGENT = None
"""TODO(Kiro): 啟動時呼叫 create_whatif_agent() 賦值，全域重複使用不每次 request 重建。"""


def _build_prompt(context: W1Context) -> str:
    """把 W1Context（history + assumptions + new_message）組成一段 prompt。"""
    raise NotImplementedError("見 W1-whatif-agent/design.md 第六節")


def process_whatif(context: W1Context) -> W1Response:
    """呼叫 WHATIF_AGENT(prompt) → format_response()。LLM 呼叫失敗時回傳
    錯誤用的 W1Response，不得讓例外往上拋（永不沉默原則）。
    """
    raise NotImplementedError("見 W1-whatif-agent/design.md 第六節")


def process_whatif_request(session_id: str, content: str, ws_broadcaster=None) -> W1Response:
    """由 orchestrator.handle_user_query() 呼叫的對外入口。

    流程：W2.handle_message() 組上下文 → （可選）推播 loading 進度
    （額外通知，ws_broadcaster 不可用時直接跳過）→ process_whatif() →
    W2.record_response() → 回傳給呼叫端組進 POST /api/what-if 的回應。
    """
    raise NotImplementedError("見 W1-whatif-agent/design.md 第十節")
