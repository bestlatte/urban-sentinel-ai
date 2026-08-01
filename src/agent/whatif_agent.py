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


def records_with_report() -> list:
    """所有**已經產出建議書**的進行中決策週期，最新的排在最前面。

    [2026-08-02] 這是「加問模式 vs 預測模式」的判斷依據。

    使用者的定案：不必確認他正在看哪一份 report——只要 Reports 區裡有 report，
    就該走加問那條路；沒有才走預測。前端 `_allDecisions`（Reports 分頁的資料源）
    是由 `decision.completed.v1` 填的，跟後端 `active_incidents` 中
    `decision_result` 有值的那些一一對應，所以這裡掃後端就等於掃畫面。

    這麼改之後，前端有沒有正確傳 `current_trace_id` 不再是開關——傳錯最壞只是
    多事件時選錯一份當主要參照，不會像原本那樣整個掉回「沒有任何事實」。

    排序用 `trace_id`：格式是 `TR-YYYYmmdd-HHMM-NNNN`（見 `orchestrator`），
    字串排序即時間排序，末四碼流水號讓同分鐘內的週期也分得出先後。
    """
    try:
        from src import orchestrator

        records = [
            r
            for r in orchestrator.get_global_state().active_incidents.values()
            if r.decision_result is not None and r.bundle_snapshot is not None
        ]
        return sorted(records, key=lambda r: r.trace_id or "", reverse=True)
    except Exception:  # noqa: BLE001 - 取不到只影響回答豐富度，不能中斷對話
        logger.debug("列舉決策週期失敗", exc_info=True)
        return []


def _current_incident_record():
    """挑一份決策週期紀錄當作「主要參照」（沒有任何一份時回 None）。

    [2026-08-02 不再硬綁 `current_trace_id`]
    ----------------------------------------
    原本這裡是「ContextVar 取不到 trace_id 就回 None」。那讓前端變成一個開關：
    `switchReportTab()` 沒有同步 `ChatState.currentTraceId`（實際上就是沒有），
    使用者切到第二份報告再發問，後端拿到的還是第一份的 id；更糟的是任何一次
    沒帶到 id，chatbot 就退回「手上什麼事實都沒有」的狀態，開始憑空講話。

    現在 trace_id 降級成**消歧提示**：對得上就用它（多事件時幫忙選對那份），
    對不上或根本沒傳，就用最新的那一份。
    """
    records = records_with_report()
    if not records:
        return None

    try:
        from src import orchestrator

        trace_id = orchestrator._current_trace_ctx.get()
        if trace_id is not None:
            for record in records:
                if record.trace_id == trace_id:
                    return record
    except Exception:  # noqa: BLE001
        logger.debug("讀取 current_trace_id 失敗，改用最新的決策週期", exc_info=True)

    return records[0]


def snapshot_of(record) -> dict | None:
    """把「回答當下的世界」凍結成一份可比對的 dict。

    [2026-08-02] 存這份是為了讓下一輪 diff 得出「情況變了什麼」。欄位只挑
    **會改變處置決定**的那些——飽和度小數點後的抖動不該讓系統跳出來宣告變化，
    但主線換人、變成無路可替補、建議書改版一定要講。

    刻意是純量 dict：session 是純記憶體的，若存物件參照，`decision_result`
    一被替換快照就跟著變，diff 永遠是空的。
    """
    if record is None:
        return None
    decision = getattr(record, "decision_result", None)
    if decision is None:
        return None

    routes = getattr(decision, "routes", None)
    ete = getattr(decision, "ete", None)
    incident = getattr(record, "incident", None)

    def _cand(c):
        if c is None:
            return None
        return {
            "segment_id": c.segment_id,
            "name": c.name,
            "saturation_score": c.saturation_score,
        }

    report = getattr(decision, "control_center_report", None)
    return {
        "trace_id": getattr(record, "trace_id", None),
        "event_id": getattr(incident, "event_id", None),
        "as_of": incident.timestamp.isoformat() if incident is not None else None,
        "primary": _cand(getattr(routes, "primary", None)) if routes else None,
        "secondary": _cand(getattr(routes, "secondary", None)) if routes else None,
        "no_feasible_route": bool(getattr(routes, "no_feasible_route", False)) if routes else False,
        "all_alternatives_saturated": (
            bool(getattr(routes, "all_alternatives_saturated", False)) if routes else False
        ),
        "replan_count": getattr(record, "route_replan_count", 0),
        "ete_minutes": getattr(ete, "minutes", None),
        "recovery_at": getattr(ete, "recovery_at", None),
        # 只存長度而不是全文：用來判斷「改版了沒」已經夠，存全文會讓每輪的
        # session 都拖著一份 500~600 字的副本。
        "report_len": len(report) if isinstance(report, str) else 0,
    }


def _fmt_route(c) -> str:
    if not c:
        return "無"
    sat = c.get("saturation_score")
    return f"{c.get('name') or c.get('segment_id')}（飽和度 {sat}）" if sat is not None else (
        c.get("name") or c.get("segment_id") or "無"
    )


def build_change_block(record, last_snapshot: dict | None) -> str | None:
    """「自你上一次回答以來，世界變了什麼」。沒有實質變化時回 None。

    [2026-08-02 新增]
    -----------------
    使用者的要求：「我的 report 隨著時間更改，我追問 chatbot 情況他應該要可以
    知道情況改變了給我新的東西。」

    在此之前，模型手上有的是：最新的事實區塊 + 舊回答原文，兩者互相矛盾，
    而**沒有任何一句話告訴它哪個是現在**。它只能猜，通常猜錯，或者兩個數字
    都講一次讓使用者更混亂。

    「實質變化」的定義刻意收窄（使用者選的是「只在實質改變時主動說」）：
    主/次線換人、無路可替補翻轉、重規劃次數增加、ETE 變動、建議書改版。
    **單純時間前進或飽和度小幅波動不算**——每輪都宣告一次「時間過了 3 分鐘」
    只會讓真正重要的那次被當成雜訊略過。
    """
    if not last_snapshot:
        return None
    now_snap = snapshot_of(record)
    if not now_snap:
        return None

    # 換了一起事件在看，就不是「同一件事的變化」，diff 沒有意義
    if now_snap.get("trace_id") != last_snapshot.get("trace_id"):
        return None

    changes: list[str] = []

    old_primary, new_primary = last_snapshot.get("primary"), now_snap.get("primary")
    if (old_primary or {}).get("segment_id") != (new_primary or {}).get("segment_id"):
        changes.append(f"- 主要替代路線：{_fmt_route(old_primary)} → {_fmt_route(new_primary)}")

    old_secondary, new_secondary = last_snapshot.get("secondary"), now_snap.get("secondary")
    if (old_secondary or {}).get("segment_id") != (new_secondary or {}).get("segment_id"):
        changes.append(f"- 次要替代路線：{_fmt_route(old_secondary)} → {_fmt_route(new_secondary)}")

    if not last_snapshot.get("all_alternatives_saturated") and now_snap.get("all_alternatives_saturated"):
        changes.append("- ⚠️ 周邊候選路段已全數飽和，**目前無路段可以替補**；現行主/次線為 SOP-2 §2a 例外的權宜指派")
    elif last_snapshot.get("all_alternatives_saturated") and not now_snap.get("all_alternatives_saturated"):
        changes.append("- 已重新找到未飽和的替代路段，脫離「無路可替補」狀態")

    if not last_snapshot.get("no_feasible_route") and now_snap.get("no_feasible_route"):
        changes.append("- ⚠️ 所有候選路段均被排除，已無可行替代路線")

    old_replans = last_snapshot.get("replan_count") or 0
    new_replans = now_snap.get("replan_count") or 0
    if new_replans > old_replans:
        changes.append(f"- 本事件已再重新規劃 {new_replans - old_replans} 次（累計 {new_replans} 次）")

    old_ete, new_ete = last_snapshot.get("ete_minutes"), now_snap.get("ete_minutes")
    if old_ete != new_ete and new_ete is not None:
        changes.append(
            f"- 預計排除時間：{old_ete} 分 → {new_ete} 分"
            f"（預計恢復 {now_snap.get('recovery_at')}）"
        )

    if last_snapshot.get("report_len") != now_snap.get("report_len"):
        changes.append("- 交控建議書已更新，事實區塊引用的是最新版本")

    if not changes:
        return None

    lines = ["=== 自你上一次回答以來的變化（由系統計算，必須主動告知使用者）==="]
    old_as_of, new_as_of = last_snapshot.get("as_of"), now_snap.get("as_of")
    if old_as_of and new_as_of and old_as_of != new_as_of:
        lines.append(f"- 評估時刻：{old_as_of[11:16]} → {new_as_of[11:16]}")
    lines.extend(changes)
    lines.append(
        "上一輪的回答依據的是變化前的路況。與本區塊衝突時一律以本區塊為準，"
        "並且**必須在回覆開頭用一句話主動說明情況已改變**，不可以只是默默換掉數字。"
    )
    return "\n".join(lines)


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


_AMBIENT_TOP_N = 5
"""態勢區塊列出前幾條最壅塞的路段。5 條足以看出「哪裡在燒」，再多就變成
把整份資料倒進 prompt——那正是我們在 `reasoning-chain.js` 拿掉「命中 N 條」
時判定為無用的東西。"""

_MAX_EXTRA_REPORTS = 2
"""除了主要參照那份以外，最多再附幾份建議書。

每份 500~600 字，兩三份對 context 不構成壓力；再多就開始稀釋真正被問到的那份。
"""


def build_ambient_facts_block() -> str | None:
    """沒有任何進行中事件時的態勢事實區塊（**預測模式**的依據）。

    [2026-08-02 新增] 使用者的要求是：「若沒有 report，我們的 chatbot 也要給出
    預測，但要合乎我們的邏輯」。

    原本沒有事件時 `build_cycle_facts_block()` 直接回 `None`，prompt 裡一個數字
    都沒有。模型手上沒有事實卻仍被要求回答路況問題，結果就是編——而編出來的
    數字跟 Dashboard 上的圖表對不起來。

    這個區塊給的是**此刻的全市態勢**：評估時刻、應變等級、最壅塞的幾條路段、
    人流吃緊的站點。全部走跟決策週期同一支 `evaluate_rules()`，所以它講的數字
    跟 Dashboard 的 KPI 必然同源。預測本身仍然只能由 `simulate_scenario` 算
    （嚴格規則第 2 條沒有放寬），這裡只是讓它有個立足點。

    評估時刻沿用 `whatif_engine.resolve_scenario_as_of()`（傳 `incident=None`）
    ——模擬器在跑就用模擬器時刻，沒在跑就用資料集最新時刻。刻意**不**直接用
    `clock.now()`：模擬器關掉時 `clock.now()` 回的是真實時間（例如 2026-08-02
    凌晨兩點），而資料集是 2026-05-20 傍晚到深夜的，區塊會寫著「評估時刻
    02:12」卻列出 23:30 的路況。這裡跟 What-if 重算走同一支解析，兩邊講的
    時刻必然一致。
    """
    try:
        from src import orchestrator
        from src.whatif_engine import resolve_scenario_as_of

        bundle = orchestrator.GATEWAY.load_data()
        as_of, as_of_reason = resolve_scenario_as_of(bundle, None)
        sensing = orchestrator.GATEWAY.evaluate_rules(bundle, None, as_of)

        lines = [
            "=== 目前全市態勢（無進行中事件，由系統計算，不得改寫）===",
            f"評估時刻：{as_of:%Y-%m-%d %H:%M}（{as_of_reason}）",
            f"應變等級：{getattr(sensing, 'traffic_level', None) or '正常'}",
        ]

        # 最壅塞的幾條路段。刻意不用 `sensing.rule_hits`——那裡只有**跨過門檻**
        # 的，都沒超標時整個區塊會空掉，但「現在最塞的是哪幾條」即使全部低於
        # 門檻也還是有意義的答案。
        #
        # 每條路段取 `as_of` 當下（含）之前最新的那筆，等同 as-of 查詢的語意。
        latest_by_segment = {}
        for record in bundle.traffic:
            if record.saturation_score is None or record.timestamp > as_of:
                continue
            prev = latest_by_segment.get(record.segment_id)
            if prev is None or record.timestamp > prev.timestamp:
                latest_by_segment[record.segment_id] = record

        top = sorted(
            latest_by_segment.values(),
            key=lambda r: -r.saturation_score,
        )[:_AMBIENT_TOP_N]
        if top:
            names = {r.segment_id: r.name for r in bundle.road_network}
            lines.append("目前飽和度最高的路段：")
            for record in top:
                seg = record.segment_id
                lines.append(
                    f"- {names.get(seg, seg)}（{seg}）飽和度 {record.saturation_score:.2f}"
                    f"　車道 {getattr(record, 'lane_status', '—')}"
                )

        hits = getattr(sensing, "rule_hits", None) or []
        if hits:
            lines.append(f"此刻跨過門檻的條款共 {len(hits)} 條（屬全市背景，非單一事件所致）。")

        lines.append(
            "目前沒有任何進行中的事件，也沒有已產出的交控建議書。"
            "使用者若問「會不會塞」「等一下怎樣」這類前瞻問題，"
            "必須呼叫 simulate_scenario 重算，不可自行從上面的數字外推。"
        )
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 - 同上，降級成「沒有事實區塊」而不是中斷
        logger.warning("組裝全市態勢區塊失敗，本次回答不帶事實上下文", exc_info=True)
        return None


def build_facts_context(record) -> str | None:
    """依「Reports 裡有沒有 report」選事實區塊。

    有 report → 加問模式：建議書全文 + 該週期的確定性事實 + 風險推演
    沒 report → 預測模式：此刻的全市態勢

    多起事件時把其餘幾份建議書也附上（`_MAX_EXTRA_REPORTS` 份為限）。使用者
    問「這起事件怎麼辦」時我們並不知道他指的是哪一起，手上有全部才答得準；
    每份 500~600 字，兩三份對 context 不構成壓力。
    """
    if record is None:
        return build_ambient_facts_block()

    primary = build_cycle_facts_block(record)
    if primary is None:
        # 週期還在跑、還沒到 PUSH 階段（`build_cycle_facts_block` 會回 None）。
        # 此時給態勢比給半套事實好——半套事實模型會拿來當完整的講。
        return build_ambient_facts_block()

    parts = [primary]

    others = [r for r in records_with_report() if r.trace_id != record.trace_id]
    for other in others[:_MAX_EXTRA_REPORTS]:
        decision = other.decision_result
        if decision is None or not decision.control_center_report:
            continue
        location = getattr(other.incident, "location", None) or other.trace_id
        parts.append(
            f"另一起進行中事件（{location}）已產出的交控建議書：\n"
            f"{decision.control_center_report}"
        )
    if others:
        parts.append(
            f"現場共有 {len(others) + 1} 起進行中事件。使用者的問題若沒有指明是哪一起，"
            "先確認再回答，不要把不同事件的數字混在一起講。"
        )

    return "\n\n".join(parts)



def _build_prompt(
    context,
    facts_block: str | None = None,
    change_block: str | None = None,
) -> str:
    """把 W1Context（history + assumptions + new_message）與當前週期事實組成 prompt。"""
    parts = []

    if facts_block:
        # 態勢區塊自己帶標題（它講的不是「當前決策週期」而是「全市現況」），
        # 只有週期事實需要在這裡補一行標題。
        if not facts_block.lstrip().startswith("==="):
            parts.append("=== 當前決策週期的確定性事實（由系統計算，不得改寫）===")
        parts.append(facts_block)
        parts.append(
            "以上數值由系統決定性模組算出，你只能引用不能修改。"
            "若使用者的假設會改變這些數值，必須呼叫 simulate_scenario 重算，不可自行推估。"
        )
        parts.append("")

    # 變化區塊放在事實之後、歷史之前：讀到歷史那些舊數字時，模型已經先知道
    # 「下面這些話是變化前講的」。順序顛倒的話它會先把舊答案當成現況吸收進去。
    if change_block:
        parts.append(change_block)
        parts.append("")

    if context.history:
        parts.append("=== 對話歷史 ===")
        for turn in context.history:
            parts.append(f"使用者：{turn.user_message}")
            parts.append(f"顧問：{turn.ai_response}")
        if change_block:
            parts.append(
                "（注意：以上回答是在情況改變**之前**給的，其中的路線與數字可能已經過時，"
                "以事實區塊與變化區塊為準。）"
            )
        parts.append("")

    scope = getattr(context, "assumption_scope", "carry")
    dropped = getattr(context, "dropped_assumptions", None) or {}

    if context.accumulated_assumptions:
        parts.append("=== 目前生效的假設條件 ===")
        for key, value in context.accumulated_assumptions.items():
            parts.append(f"- {key} = {value}")
        parts.append(
            "使用者這次的新問題若延續上述假設，呼叫 simulate_scenario 時必須把"
            "這些假設一併帶入 assumptions，不能只帶本次新增的那一項。"
        )
        parts.append("")

    # 假設被換掉時一定要講。少了這一段，模型會沿用對話歷史裡那個已經失效的
    # 假設繼續推論——歷史還在 prompt 裡，它不知道那個前提已經作廢。
    if scope == "replace" and dropped:
        parts.append("=== 假設情境已重置 ===")
        parts.append(
            "使用者提出的是一個**新的、獨立的**假設情境，以下先前的假設已不再生效，"
            "不得帶入本次的 simulate_scenario，也不得在推論中沿用："
        )
        for key, value in dropped.items():
            parts.append(f"- （已失效）{key} = {value}")
        parts.append(
            "請在回覆中用一句話讓使用者知道先前的假設已被清除，"
            "若他其實是想疊加，可以請他說明「同時」或「再加上」。"
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

    # [2026-08-02] 事實區塊改由 `build_facts_context()` 決定走哪一條：
    # Reports 裡有 report → 加問模式（建議書 + 週期事實），沒有 → 預測模式
    # （全市態勢）。原本是直接呼叫 `build_cycle_facts_block()`，沒有事件時
    # 回 None，模型手上一個數字都沒有還被要求回答路況問題。
    record = _current_incident_record()
    facts_block = build_facts_context(record)
    # 「自上次回答以來的變化」。沒有實質變化時回 None，prompt 就不會多這一段
    # ——使用者選的是「只在實質改變時主動說」，每輪都掛一段變化摘要會讓
    # 真正重要的那次被當成雜訊。
    change_block = build_change_block(record, getattr(context, "last_snapshot", None))
    prompt = _build_prompt(context, facts_block, change_block)

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

    _attach_session_context(response, context, record, change_block)
    return response


def _attach_session_context(response, context, record, change_block: str | None) -> None:
    """把「這輪依據哪個時刻、哪些假設生效、情況有沒有變」掛回回覆。

    這三件事在此之前全部只存在於後端記憶體：使用者看不到系統拿什麼在算，
    也看不出眼前這段話是幾點鐘的世界。就地修改，任何失敗都只是少幾個欄位。
    """
    try:
        snap = snapshot_of(record)
        if snap:
            response.context_as_of = snap.get("as_of")
        response.active_assumptions = dict(getattr(context, "accumulated_assumptions", None) or {})
        response.dropped_assumptions = dict(getattr(context, "dropped_assumptions", None) or {})
        response.situation_changed = bool(change_block)
    except Exception:  # noqa: BLE001
        logger.debug("掛載對話上下文欄位失敗", exc_info=True)


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
    #
    # `assumption_scope` 一定要傳下去：`handle_message()` 已經決定這輪不把舊假設
    # 帶進 prompt 了，若 session 裡還留著，下一輪的追問（carry）會把它們原封不動
    # 撈回來，等於白清一場。
    #
    # `context_snapshot` 是下一輪 diff 「情況變了什麼」的基準，必須存**回答當下**
    # 的世界，不是下次讀取時的世界。
    record_response(
        session_id=session_id,
        user_message=content,
        ai_response=response.summary,
        triggered_sops=[s.get("section_number", 0) for s in response.triggered_sops]
        if response.triggered_sops
        else None,
        new_assumptions=_assumptions_from_response(response),
        assumption_scope=getattr(context, "assumption_scope", "carry"),
        context_snapshot=snapshot_of(_current_incident_record()),
    )

    # 回覆帶回 session 裡**最終**生效的假設（前端 chips 依此渲染）。
    # 不能沿用 context 那份——LLM 這輪可能又新增了假設，那些也要顯示。
    try:
        from src.session.session_manager import get_assumptions

        response.active_assumptions = get_assumptions(session_id)
    except Exception:  # noqa: BLE001
        logger.debug("讀取生效假設失敗", exc_info=True)

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
