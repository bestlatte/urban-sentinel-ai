"""W1 的 Strands @tool：query_sop、simulate_scenario。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md` 第四節（已修正版）。
"""

from __future__ import annotations

from strands import tool


@tool
def query_sop(question: str) -> dict:
    """查詢 SOP 條款。輸入自然語言問題，回傳最相關的 SOP 條款原文。

    何時使用：使用者問 SOP 規則內容、需要確認某情境觸發哪條 SOP、
    What-if 問題中需要引用條款依據。
    """
    from src.bedrock_service.sop_retriever import query_sop as _query

    result = _query(question)
    return {
        "sections": [
            {
                "section_number": s.section_number,
                "title": s.title,
                "content": s.content,
            }
            for s in result.sections
        ],
        "retrieval_source": result.retrieval_source,
    }


@tool
def simulate_scenario(assumptions: dict, question: str) -> dict:
    """用假設參數模擬交通情境，重新計算路線、ETE、觸發條款。

    何時使用：使用者提出 What-if 假設、需要精確的路線計算或 ETE 數值。

    Args:
        assumptions: 格式 {"entity.field": value}，例如
            {"BS_MRT_BL17.User_Count": 40000, "RD_TPE_002.status": "Closed"}
        question: 使用者原始問題（供理解上下文）

    [2026-07-28總架構師補充] 呼叫 `src/whatif_engine.run_scenario()`——那裡把
    apply_scenario_overrides + 既有的 evaluate_rules/plan_route/calculate_ete
    串起來，不經過 orchestrator.py（避免 Orchestrator→W1→Orchestrator 循環依賴），
    也不在 routing.py/rules.py/reporting.py 裡另開一套「_with_overrides」版本。

    incident/bundle 目前哪裡來還沒定案（需要目前作用中的事件與 as-of 快照）——
    TODO(Kiro): 從 W2Context 或 orchestrator 的 GlobalState 取得目前作用中的
    incident 與 bundle，這裡先假設有一個 `get_current_context()` 可用。
    """
    try:
        from src import orchestrator
        from src.whatif_engine import run_scenario

        incident, bundle = _get_current_context()  # TODO(Kiro): 見本函式 docstring
        return run_scenario(bundle, incident, assumptions, orchestrator.GATEWAY)
    except Exception as exc:  # noqa: BLE001 - 保底模式，任何失敗都要能降級不中斷對話
        return {
            "status": "unavailable",
            "message": f"決策模組暫時不可用：{exc}",
            "fallback": True,
        }


def _get_current_context():
    """TODO(Kiro): 回傳 (目前作用中的 Incident, 目前的 NormalizedDataBundle)。
    來源待定——最可能是 orchestrator.get_global_state() 或最近一次
    handle_incident() 的快取結果，需要在實作階段確認。
    """
    raise NotImplementedError("見 simulate_scenario docstring")
