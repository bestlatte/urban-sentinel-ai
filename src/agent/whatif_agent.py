"""W1 主邏輯：建立 Agent 實例、process_whatif()、process_whatif_request()。

參考 spec：`.kiro/specs/m3-bedrock-advisor/W1-whatif-agent/design.md`
（已修正版第五、六、十節）。

**進場方式（重要，不要照抄該資料夾 tasks.md 舊版寫法）**：
`POST /api/what-if` 收到請求 → `orchestrator.handle_user_query()`（見
`m4-explanation-chain-and-orchestrator/SPEC-O3` §4）判斷是前瞻假設問題 →
呼叫本檔的 `process_whatif_request()` → 同步回傳完整結果。不是 W1 自己接
WebSocket 訊息、自己決定要不要處理。

[2026-08-01 大幅修正，逐項說明]
------------------------------
1. **保底模式**：`USE_BEDROCK=false` 時直接降級，不再送出注定失敗的請求。
   A2 規劃器、`reporting`、`decision_trace` 三處本來就有這個檢查，只有 W1 沒有
   （`00-tech-stack.md` §6 的保底模式等於對 W1 無效）。
2. **逾時護欄**：Agent 呼叫包 `llm.run_with_timeout()`。原本是裸的同步阻塞，
   現場網路一抖對話就永久卡住。
3. **Agent 不再全域共用**：改成每次請求新建。原本 `WHATIF_AGENT` 是全域單例，
   而 `agent.messages` 會累積對話歷史——所有使用者、所有 session 共用同一份
   歷史，既跨 session 洩漏內容，也會一路長到爆 context window。W1 的對話歷史
   本來就由 W2 `session_manager` 管並注入 prompt，Agent 自己再記一份是多餘的。
   （模型物件仍然快取，見 `llm.get_strands_model()`。）
4. **關掉 callback_handler**：Strands 預設會把串流輸出 print 到 stdout，在
   Windows cp950 主控台遇到 emoji 會拋 `UnicodeEncodeError` 讓整次呼叫失敗。
   實測會發生（LLM 回覆帶 📋 就中），W1 不需要串流列印，直接關掉。
5. **方案A 共用事實管線**：把當前決策週期實際算出來的事實
   （`reporting.build_facts_block()`，跟交控建議書用的是同一份）注入 prompt，
   讓 W1 回答時引用的數字跟建議書、決策軌跡三處必然一致。
6. **方案B 情境建議書**：使用者要求出報告時，用重算後的結果跑同一支
   `reporting.generate_report()`，產出可與正式建議書並排比較的假設情境版本。
"""

from __future__ import annotations

import logging

from src.agent.response_formatter import (
    ToolInvocation,
    W1Response,
    format_response,
)
from src.agent.system_prompt import SYSTEM_PROMPT, DEFAULT_QUESTIONS
from src.agent.tools import query_sop, simulate_scenario
from src.llm import AGENT_TIMEOUT_S, bedrock_enabled, get_strands_model, run_with_timeout

logger = logging.getLogger(__name__)

REPORT_INTENT_WORDS = (
    "建議書",
    "報告書",
    "交控建議",
    "產出報告",
    "出一份報告",
    "生成報告",
    "寫一份報告",
)
"""方案B 的觸發詞。確定性關鍵字比對、零 LLM——跟 `orchestrator.handle_user_query()`
的三分支路由（SPEC-O3 §4）同一種做法，路由決策不交給模型。

刻意不收單獨的「報告」兩字：「這份報告怎麼算的」是回溯追問，不是要產生新文件。
"""


def create_whatif_agent():
    """建立一個**全新的** W1 Agent 實例。

    每次呼叫都要新的（理由見模組 docstring 第 3 點）。模型物件由
    `llm.get_strands_model()` 快取，所以這裡不會每次都開 boto3 client。
    """
    from strands import Agent

    return Agent(
        model=get_strands_model(),
        tools=[query_sop, simulate_scenario],
        system_prompt=SYSTEM_PROMPT,
        # 見模組 docstring 第 4 點：預設 handler 會 print 到 stdout，Windows 會炸。
        callback_handler=None,
    )


WHATIF_AGENT = None
"""[已淘汰] 保留這個名字只為了不讓舊的 import 直接 ImportError。

任何讀到這個變數的程式都拿到 None——請改呼叫 `create_whatif_agent()`。
（`加分項_AgentCore_Runtime部署.md` §6 記載過有人照抄 `WHATIF_AGENT(question)`
然後在雲端拿到 `TypeError: 'NoneType' object is not callable`。）
"""


# ---------------------------------------------------------------------------
# 方案A：共用事實管線
# ---------------------------------------------------------------------------


def _current_incident_record():
    """取得使用者目前正在查看的決策週期紀錄（沒有則 None）。

    走 `orchestrator._current_trace_ctx`（`handle_user_query()` 在轉發給 W1
    之前設定的 ContextVar），跟 `agent/tools.py::_get_current_context()` 同一條路。
    """
    try:
        from src import orchestrator

        trace_id = orchestrator._current_trace_ctx.get()
        if trace_id is None:
            return None
        for record in orchestrator.get_global_state().active_incidents.values():
            if record.trace_id == trace_id:
                return record
    except Exception:  # noqa: BLE001 - 取不到上下文只影響回答豐富度，不能中斷對話
        logger.debug("取得當前決策週期失敗", exc_info=True)
    return None


def build_cycle_facts_block(record) -> str | None:
    """把當前決策週期的確定性事實組成文字塊（方案A 的核心）。

    刻意重用 `reporting.build_facts_block()` ——**跟交控建議書用的是同一個函式**。
    這是 SPEC-00 鐵律①「LLM 只表達、不改寫」在對話層的落實：W1 講的數字不可能
    跟建議書講的不一樣，因為兩者字面上來自同一次組裝。

    `sensing` 需要重算（`DecisionResult` 沒有帶 `SensingResult`），但那是純函式
    運算、無 I/O、無 LLM，且輸入是週期當下的 `bundle_snapshot`，結果必然等同
    當初那一次——不是「重新判斷」，只是把同樣的算式再跑一遍。
    """
    if record is None or record.bundle_snapshot is None:
        return None

    decision = record.decision_result
    if decision is None or decision.ete is None:
        # 週期還沒跑到 PUSH 階段。此時給不出完整事實，不如不給——半套事實比
        # 沒有事實更危險（模型會拿殘缺數字當完整的講）。
        return None

    try:
        from src import orchestrator
        from src.reporting import build_facts_block
        from src.risk_projection import build_risk_block_from_dict

        sensing = orchestrator.GATEWAY.evaluate_rules(record.bundle_snapshot, record.incident)
        facts = build_facts_block(
            incident=record.incident,
            sensing=sensing,
            route_plan=decision.routes,
            ete=decision.ete,
            bundle=record.bundle_snapshot,
        )

        # [2026-08-01] 把二階效應推演一併注入。
        #
        # 不注入的後果實測到了：使用者問「改道之後會有什麼問題嗎？」，模型回
        # 「主要替代路線市民大道飽和度 **0.67**，勉強夠用」——那個數字是**編的**，
        # 實際是 0.78，而且推演顯示它在 25 分鐘內會到 0.978。
        #
        # 模型不是在說謊，是手上真的沒有這份資料：推演結果那時候只放進
        # `DecisionResult`（給前端畫圖），從來沒有進過 W1 的 prompt。
        # 前端畫著正確的圖，對話框裡講著錯誤的數字，兩者並排出現。
        risk_block = build_risk_block_from_dict(decision.projected_risks)

        # [2026-08-01] 把**建議書全文**也放進事實區塊。
        #
        # 使用者的原話：「注入事件觸發報告書和 chatbot 問同個問題，給出的建議不同」。
        # 修好 trace_id 之後兩邊至少算同一個時刻了，但仍有兩個發散源：
        # 建議書走 reporting.py + haiku-4-5 + report.txt，chatbot 走 W1 + sonnet-4-5
        # + advisor.txt——不同模型、不同 prompt，就算數字一樣，取捨與措辭也會不同。
        #
        # 最直接的收斂方式是讓 chatbot 看得到建議書本身。追問「這起事件怎麼辦」時，
        # 它引用的就是長官螢幕上那份，而不是自己重新想一套。
        parts = [facts]
        if risk_block:
            parts.append(risk_block)
        if decision.control_center_report:
            parts.append(
                "本週期已產出的交控建議書全文（追問這起事件時**以本文為準**，"
                "不要另外提出不同的處置方案）：\n"
                f"{decision.control_center_report}"
            )
        return "\n\n".join(parts)
    except Exception:  # noqa: BLE001 - 同上，降級成「沒有事實區塊」而不是中斷
        logger.warning("組裝當前週期事實區塊失敗，本次回答不帶事實上下文", exc_info=True)
        return None


def _build_prompt(context, facts_block: str | None = None) -> str:
    """把 W1Context（history + assumptions + new_message）與當前週期事實組成 prompt。"""
    parts = []

    if facts_block:
        parts.append("=== 當前決策週期的確定性事實（由系統計算，不得改寫）===")
        parts.append(facts_block)
        parts.append(
            "以上數值由系統決定性模組算出，你只能引用不能修改。"
            "若使用者的假設會改變這些數值，必須呼叫 simulate_scenario 重算，不可自行推估。"
        )
        parts.append("")

    if context.history:
        parts.append("=== 對話歷史 ===")
        for turn in context.history:
            parts.append(f"使用者：{turn.user_message}")
            parts.append(f"顧問：{turn.ai_response}")
        parts.append("")

    if context.accumulated_assumptions:
        parts.append("=== 目前累積的假設條件 ===")
        for key, value in context.accumulated_assumptions.items():
            parts.append(f"- {key} = {value}")
        parts.append(
            "使用者這次的新問題若延續上述假設，呼叫 simulate_scenario 時必須把"
            "累積假設一併帶入 assumptions，不能只帶本次新增的那一項。"
        )
        parts.append("")

    parts.append(f"使用者新問題：{context.new_message}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def wants_scenario_report(text: str) -> bool:
    """使用者是否明確要求產生一份情境建議書（方案B 觸發判斷）。"""
    return any(word in text for word in REPORT_INTENT_WORDS)


INCOMPLETE_INPUT_PATTERNS = (
    "如果",
    "假如",
    "假設",
    "要是",
    "萬一",
    "會怎樣",
    "會怎麼樣",
    "怎麼辦",
    "呢",
    "?",
    "？",
)
"""只由這些詞（或其組合）構成的輸入視為不完整。

「如果」「怎麼辦」「如果呢？」這種輸入沒有任何可回答的內容，但它們含前瞻詞，
會被 `orchestrator.handle_user_query()` 路由到 W1，然後走完整 Agent 流程——
實測花 30 秒跑多輪 tool call，生出一篇「請問您想問什麼呢？」的長文，還附上
一堆它自己編的範例問題。使用者的體感是「打錯字就卡住三十秒」。

刻意跟 `orchestrator._FORWARD_LOOKING_WORDS` 分開維護：那份清單的用途是
「這句話**是不是**前瞻問題」，這份是「這句話**有沒有內容**」。合併會讓其中
一邊的調整意外影響另一邊。
"""

_INCOMPLETE_TRAILING_CHARS = " 　,，.。!！、;；:：~～\n\t"


def is_incomplete_input(text: str) -> bool:
    """輸入是否短到沒有可回答的內容（P2 韌性：0 秒短路，不打 LLM）。

    判斷是確定性的、零 LLM——跟 SPEC-O3 §4 的三分支路由同一種做法。

    [2026-08-01 修正：原本的長度門檻把正常問題擋在門外]
    --------------------------------------------------
    原本第一關是 `len(stripped) < MIN_MEANINGFUL_LENGTH`（4 個字元）。那是拿
    「長度」當「有沒有內容」的代理指標，但中文問句密度很高——實測這些**完整
    且可回答**的問題全部被判定成不完整輸入：

        「你是誰」  (3) → 回「看起來問題還沒打完…」
        「你好」    (2) → 同上
        「塞車」    (2) → 同上

    使用者問「你是誰」拿到一串 What-if 範例問句，看起來就像 chatbot 壞了。

    現在只保留**內容判斷**：把前瞻詞與標點拿掉之後還剩下實質字元，就是有內容。
    這正是原本第二關在做的事，第一關的長度門檻是多餘且有害的。

        「如果」    → 殘餘 ""     → 不完整 ✓
        「如果呢？」→ 殘餘 ""     → 不完整 ✓
        「你是誰」  → 殘餘 "你是誰" → 完整 ✓
    """
    stripped = (text or "").strip()
    if not stripped:
        return True

    # 把前瞻詞與標點全部拿掉，看還剩下什麼實質內容
    residue = stripped
    for token in INCOMPLETE_INPUT_PATTERNS:
        residue = residue.replace(token, "")
    residue = residue.strip(_INCOMPLETE_TRAILING_CHARS)
    return len(residue) < 2


def _incomplete_input_response() -> W1Response:
    """不完整輸入的即時回覆（0 秒，不呼叫任何 LLM）。

    刻意寫得具體：直接給三個可以點的完整問句，比「請問您想問什麼？」有用得多
    ——後者只是把問題丟回給使用者。這些範例對應 `data/` 裡真實存在的實體
    （RD_TPE_004 市民大道四段、BS_MRT_BL17 市政府站），所以點下去一定問得動。
    """
    return W1Response(
        intent_type="chitchat",
        summary=(
            "看起來問題還沒打完。請描述完整的假設情境，例如：\n\n"
            "- 如果市民大道四段的飽和度上升到 0.98，替代路線還夠用嗎？\n"
            "- 如果市政府站人流增加到 40000 人，會觸發哪些條款？\n"
            "- 如果光復南路封閉，ETE 會變多久？"
        ),
        suggested_questions=[
            "如果市民大道四段飽和度到 0.98，替代路線還夠嗎？",
            "如果市政府站人流到 40000，會觸發哪些條款？",
            "如果光復南路封閉，ETE 會變多久？",
        ],
        source_mode="full",
        tools_called=[],
    )


def process_whatif(context, timeout_s: float | None = None) -> W1Response:
    """呼叫 Agent → format_response()。LLM 呼叫失敗時回傳錯誤用的 W1Response，
    不得讓例外往上拋（永不沉默原則）。

    Args:
        context: `W1Context`
        timeout_s: 逾時秒數，預設 `llm.AGENT_TIMEOUT_S`（60s，使用者對話情境）。
            決策週期內的 advisory 呼叫會傳較短的 `llm.ADVISORY_TIMEOUT_S`——
            那裡拖的是整個事件應變的時間，不是單一使用者的等待。
    """
    budget = AGENT_TIMEOUT_S if timeout_s is None else timeout_s

    # P2 韌性：不完整輸入 0 秒回覆，不打 LLM。刻意放在最前面（連 USE_BEDROCK
    # 檢查都在它之後）——「如果」兩個字不管在什麼模式下都沒有東西可以回答。
    if is_incomplete_input(context.new_message):
        logger.info("不完整輸入，直接回提示不呼叫 LLM：%r", context.new_message)
        return _incomplete_input_response()

    # 保底模式（`00-tech-stack.md` §6）：不得真的送出 Bedrock 請求。只靠下面的
    # except 接住連線錯誤是不夠的——離線或憑證過期時每一輪對話都要先等一次逾時。
    if not bedrock_enabled():
        return _degraded_response(context, reason="USE_BEDROCK=false（保底模式）")

    record = _current_incident_record()
    facts_block = build_cycle_facts_block(record)
    prompt = _build_prompt(context, facts_block)

    try:
        agent = create_whatif_agent()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"無法建立 Strands Agent: {e}，將使用降級模式")
        return _degraded_response(context, reason=f"Agent 建立失敗: {e}")

    # [2026-08-01] W1 走 Strands，不經過 `llm.invoke_converse`，所以那裡的
    # 可用性探針涵蓋不到這條路。這裡自己回報一次，否則「Bedrock 通不通」的判斷
    # 會漏掉整個對話路徑——而對話正是 Demo 現場最常操作的功能。
    import time as _time

    from src import bedrock_status
    from src.llm import get_model_id

    _started = _time.perf_counter()
    try:
        raw_response = run_with_timeout(lambda: agent(prompt), budget, label="W1 Agent")
    except TimeoutError as e:
        # e 的訊息已含 "W1 Agent 逾時（>25s）"（label 由 run_with_timeout 帶入），
        # 不要再加一次前綴。
        logger.warning(str(e))
        bedrock_status.record_failure(e)
        return _degraded_response(context, reason=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception(f"W1 Agent 呼叫失敗: {e}")
        bedrock_status.record_failure(e)
        return _degraded_response(context, reason=f"Agent 呼叫失敗: {e}")

    bedrock_status.record_success(
        get_model_id(), int((_time.perf_counter() - _started) * 1000)
    )

    response = format_response(raw_response, context, messages=agent.messages)

    # 方案B：使用者要求出報告時，額外產出情境建議書
    if wants_scenario_report(context.new_message):
        _attach_scenario_report(response, agent.messages, record)

    return response


def _attach_scenario_report(response: W1Response, messages: list, record) -> None:
    """方案B：用重算結果跑 C1-C4 生成，把情境建議書掛回 `W1Response`。

    就地修改 `response`。任何失敗都只是「沒有報告」，不影響已經產出的對話回覆
    ——報告是加值，不能因為它失敗就把整個回答吃掉。
    """
    if record is None or record.incident is None or record.bundle_snapshot is None:
        response.scenario_report = None
        response.summary += (
            "\n\n（註：目前沒有進行中的決策週期，無法產生假設情境建議書。"
            "請先在儀表板選定一起事件。）"
        )
        return

    from src.agent.response_formatter import extract_tool_invocations

    assumptions = _merge_assumptions(extract_tool_invocations(messages)) or {}

    try:
        from src import orchestrator
        from src.whatif_engine import compute_scenario, generate_scenario_report

        outcome = compute_scenario(
            bundle=record.bundle_snapshot,
            incident=record.incident,
            overrides=assumptions,
            gateway=orchestrator.GATEWAY,
        )
        report = generate_scenario_report(
            incident=record.incident,
            outcome=outcome,
            overrides=assumptions,
            base_decision=record.decision_result,
        )
    except Exception:  # noqa: BLE001
        logger.exception("產生情境建議書失敗")
        return

    response.scenario_report = report.get("report_text")
    response.differences_from_base = report.get("differences") or []
    if response.scenario_report:
        response.intent_type = "scenario_report"


def _degraded_response(context, reason: str | None = None) -> W1Response:
    """LLM 不可用時的降級回覆：只用 query_sop 做本機 SOP 查詢。

    `reason` 只寫進日誌，不放進 `summary`——使用者不需要看到「USE_BEDROCK=false」
    這種內部旗標名稱。
    """
    if reason:
        logger.info(f"W1 降級回覆：{reason}")

    try:
        sop_result = query_sop(question=context.new_message)
        triggered_sops = sop_result.get("sections", []) if isinstance(sop_result, dict) else []
        summary = "系統暫時忙碌，以下為基於 SOP 條款的參考資訊。"
        if triggered_sops:
            for s in triggered_sops:
                summary += f"\n\n【SOP-{s['section_number']}】{s['title']}\n{s['content'][:100]}..."
    except Exception:  # noqa: BLE001
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


def _merge_assumptions(invocations: list[ToolInvocation]) -> dict[str, float | int | str] | None:
    """把所有 `simulate_scenario` 呼叫的 `assumptions` 依序合併。

    後面的呼叫覆蓋前面的同名 key——Agent 若在同一輪裡先試一組再改一組，
    使用者要的是最後那組。
    """
    merged: dict[str, float | int | str] = {}
    for inv in invocations:
        if inv.name != "simulate_scenario":
            continue
        assumptions = inv.input.get("assumptions")
        if isinstance(assumptions, dict):
            merged.update(assumptions)
    return merged or None


def process_whatif_request(
    session_id: str,
    content: str,
    correlation_id: str | None = None,
    ws_broadcaster=None,
) -> W1Response:
    """由 orchestrator.handle_user_query() 呼叫的對外入口。

    流程：W2.handle_message() 組上下文 → （可選）推播 loading 進度
    → process_whatif() → W2.record_response() → 回傳給呼叫端。
    """
    from src.session.session_manager import handle_message, record_response
    from src.agent.loading import broadcast_loading_start_sync, broadcast_loading_complete_sync

    # correlation_id 為 None 時 fallback 用 session_id，避免舊呼叫端沒傳時炸掉
    effective_correlation_id = correlation_id or session_id

    # 1. W2 組上下文
    context = handle_message(session_id, content)

    # 2. 推播 loading 開始（額外通知，不影響主流程）
    broadcast_loading_start_sync(ws_broadcaster, correlation_id=effective_correlation_id)

    # 3. W1 處理
    response = process_whatif(context)

    # 4. 推播 loading 完成
    broadcast_loading_complete_sync(ws_broadcaster, correlation_id=effective_correlation_id)

    # 5. W2 記錄回覆
    record_response(
        session_id=session_id,
        user_message=content,
        ai_response=response.summary,
        triggered_sops=[s.get("section_number", 0) for s in response.triggered_sops]
        if response.triggered_sops
        else None,
        new_assumptions=_assumptions_from_response(response),
    )

    # 6. 冗餘推播 chat.response.v1（多分頁/多人同時看同一對話的保底管道）
    if ws_broadcaster is not None:
        from dataclasses import asdict

        from src.async_bridge import dispatch

        async def _push_chat_response():
            await ws_broadcaster({
                "message_type": "chat.response.v1",
                "payload": {
                    "correlation_id": effective_correlation_id,
                    **asdict(response),
                },
            })

        # [2026-08-01] 原本是 `asyncio.get_event_loop()` + `ensure_future`，
        # 在工作執行緒下會拋 RuntimeError 並被 `except: pass` 吃掉。理由同
        # `agent/loading.py` 的說明，統一走 `async_bridge`。
        dispatch(_push_chat_response())

    return response


def _assumptions_from_response(response: W1Response) -> dict[str, float | int | str] | None:
    """取出本輪假設交給 W2 累積（原 `_extract_new_assumptions` 的 TODO）。

    [2026-08-01 補實作] 原本是 `_extract_new_assumptions()` 直接 `return None`，
    註解寫「Agent 的 tool call input 不一定能從 response 中逆推，留待 Phase 8」。
    現在逆推得到了：`simulate_scenario(assumptions={...})` 的呼叫參數就記在
    `agent.messages` 的 `toolUse.input` 裡，一字不差。

    這個函式沒實作的後果是 `session.assumptions` 永遠是空的，多輪累積假設
    （「如果 A…」→「那再加上 B 呢？」）整個功能等於不存在——`prompts/advisor.txt`
    「對話上下文」那一節明文要求的行為做不到。

    來源選 `current_data.applied_overrides`（`whatif_engine.build_data_snapshot()`
    寫的）而不是再解析一次 `agent.messages`，是為了只認**真的被模擬引擎採用的
    假設**：Agent 若提出假設但工具呼叫失敗，那組假設不該被記進 session，否則
    下一輪會帶著一組從未生效的條件繼續推，而且使用者完全看不出來。
    """
    if not isinstance(response.current_data, dict):
        return None
    applied = response.current_data.get("applied_overrides")
    return applied if isinstance(applied, dict) and applied else None
