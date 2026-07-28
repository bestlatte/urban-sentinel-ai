"""W1 What-if 問答 Agent。參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/`
（design.md 已修正版：進場方式是 orchestrator.handle_user_query() 呼叫
process_whatif_request()，不是 W1 自己接 WebSocket）。
"""

from src.agent.whatif_agent import process_whatif, process_whatif_request

__all__ = ["process_whatif", "process_whatif_request"]
