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
                "relevance_score": s.relevance_score,
                # [2026-07-28再更正：回應Kiro審查] 原本這裡漏掉 relevance_score，
                # 但 format_response() 組 SopEvidence 時這個欄位是必填——
                # local_fallback.py 用命中率算、bedrock_kb.py 用KB回傳的score，
                # 兩條路徑都有值，只是這個工具包裝函式沒有把它傳出去，已修正。
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

    [2026-07-28總架構師補充：回應Kiro審查，定案] 呼叫 `src/whatif_engine.run_scenario()`
    ——那裡把 apply_scenario_overrides + 既有的 evaluate_rules/plan_route/calculate_ete
    串起來，不經過 orchestrator.py 的函式本身（避免 Orchestrator→W1→Orchestrator
    循環依賴），但經由 `orchestrator.GATEWAY` 存取。

    `_get_current_context()`：透過 `orchestrator._current_trace_ctx`（一個
    `contextvars.ContextVar`，由 `handle_user_query()` 在轉發給 W1 之前設定）
    取得目前的 trace_id，再查 `orchestrator.GATEWAY.get_global_state()` 的
    `active_incidents` 找對應的 `IncidentRecord`。trace_id 為 None（使用者沒有
    正在查看特定事件、但問題仍含前瞻假設詞）是合理情境，這時只能做不依賴特定
    事件的模擬（incident=None，evaluate_rules 可以接受，但 plan_routes/calculate_ete
    需要 incident，`run_scenario` 遇到 incident=None 時應該只填 rule_hits，
    route_plan/ete 留 null）。
    """
    try:
        from src import orchestrator
        from src.whatif_engine import run_scenario

        incident, bundle = _get_current_context()
        return run_scenario(bundle, incident, assumptions, orchestrator.GATEWAY)
    except Exception as exc:  # noqa: BLE001 - 保底模式，任何失敗都要能降級不中斷對話
        return {
            "status": "unavailable",
            "message": f"決策模組暫時不可用：{exc}",
            "fallback": True,
        }


def _get_current_context():
    """回傳 (目前作用中的 Incident | None, 目前的 NormalizedDataBundle)。

    見 `simulate_scenario` docstring 對 trace_id 為 None 情境的說明。
    """
    from src import orchestrator

    trace_id = orchestrator._current_trace_ctx.get()
    state = orchestrator.get_global_state()

    incident = None
    bundle = None
    if trace_id is not None:
        for record in state.active_incidents.values():
            if record.trace_id == trace_id:
                incident = record.incident
                bundle = record.bundle_snapshot
                break

    if bundle is None:
        bundle = orchestrator.GATEWAY.load_data()

    return incident, bundle
