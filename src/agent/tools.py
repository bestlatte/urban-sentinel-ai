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
        assumptions: 格式 {"entity.field": value}。**欄位名必須從下列清單挑，
            不可自行縮寫或發明**：

            **路段代號對照表（務必照這張表對，不要自己推測號碼）**：
              RD_TPE_001 忠孝東路四段    RD_TPE_009 基隆路地下道
              RD_TPE_002 光復南路        RD_TPE_010 市府路
              RD_TPE_003 基隆路一段      RD_TPE_011 松壽路
              RD_TPE_004 市民大道四段    RD_TPE_012 敦化南路二段
              RD_TPE_005 仁愛路四段      RD_TPE_013 信義路五段
              RD_TPE_006 敦化南路一段    RD_TPE_014 松智路
              RD_TPE_007 松高路          RD_TPE_015 復興南路一段
              RD_TPE_008 延吉街

            不確定號碼時**直接用中文路名當 entity**（例如 "仁愛路.lane_status"），
            系統會自己對應。猜一個號碼是最糟的選項——實測發生過把「仁愛路」
            當成 RD_TPE_002（那是光復南路），整套推演算在錯的路段上，
            而回答的語氣完全看不出算錯了。

            基站：BS_MRT_BL16/BL17/BL18（捷運）、BS_TPE_101、BS_TPE_DOME（大巨蛋）、
            BS_XY_ATT、BS_XY_VIESHOW、BS_SS_PARK、BS_BUS_TERM

            路段（entity 以 RD_ 開頭，例如 RD_TPE_001 ~ RD_TPE_015）：
              saturation_score  飽和度 0.0~1.0
              avg_speed         平均速率 km/h
              vehicle_count     車輛數
              lane_status       車道狀態（Open / Closed / Blocked / Restricted）
              capacity_vph      每小時容量
              flow_direction    流向

            基站（entity 以 BS_ 開頭，例如 BS_MRT_BL17、BS_TPE_DOME）：
              user_count        人數
              growth_rate       成長率（小數，非百分比）
              roaming_user_pct  漫遊比率 0.0~1.0
              stay_time_avg     平均停留時間（分鐘）

            範例：
              {"BS_MRT_BL17.user_count": 40000}
              {"RD_TPE_004.saturation_score": 0.98}
              {"RD_TPE_002.lane_status": "Closed"}

        question: 使用者原始問題（供理解上下文）

    [2026-08-01] 上面的欄位清單是新加的。原本只給兩個範例，實測 LLM 會自己縮寫成
    `RD_TPE_004.saturation`，覆寫整個失敗、What-if 退化成「決策模組暫時不可用」。

    **這份清單必須跟 `whatif_engine.supported_fields()` 一字不差**——docstring
    就是 LLM 看到的工具描述，描述與實作一旦漂移，模型又會開始猜欄位名。
    `tests/test_whatif_agent.py::test_tool_docstring_lists_all_supported_fields`
    會擋住漂移，不要用註解「提醒自己記得同步」了事。

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
        # `question` 有兩個用途：判斷嚴重度措辭（「嚴重車禍」vs「輕微擦撞」），
        # 以及在沒有進行中事故時決定要不要合成假想事故。見 whatif_engine。
        return run_scenario(bundle, incident, assumptions, orchestrator.GATEWAY, question)
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
