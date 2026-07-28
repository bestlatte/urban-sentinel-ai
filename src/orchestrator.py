"""A1 事件分類 / A2 編排 / A4 決策留痕 / 對外路由。

**雙 spec owner，見 `.kiro/steering/04-system-architecture.md` §3 說明**：
- 核心邏輯（本檔大部分函式怎麼運作）權威來源：`.kiro/specs/m4-explanation-chain-and-orchestrator/`
  全部 6 份文件（SPEC-00 共同基礎 / SPEC-M4A 記錄層 / SPEC-M4B 生成層 /
  SPEC-O1 生命週期 / SPEC-O2 分派與編排 / SPEC-O3 對外介面）。
- 型別與命名（ModuleGateway Protocol、DecisionResult 欄位名）權威來源：
  `.kiro/specs/m5-api-orchestrator-dashboard/design.md`。
兩邊對同一件事有分歧時：編排邏輯以前者為準、欄位命名以後者為準——這條分工線
本次審查已逐一核對過，衝突都已解決並記錄在 `INDEX.md`。
"""

from __future__ import annotations

import contextvars
import os
from dataclasses import dataclass, field
from typing import Protocol

from src.models import (
    BedrockAdvisory,
    DecisionResult,
    EteEstimate,
    Incident,
    Notification,
    NormalizedDataBundle,
    RoutePlan,
    RouteRequest,
    SensingResult,
)


# ---------------------------------------------------------------------------
# ModuleGateway：M5 對 M1-M4 的邊界（m5-api-orchestrator-dashboard/design.md）
# ---------------------------------------------------------------------------


class ModuleGateway(Protocol):
    def load_data(self) -> NormalizedDataBundle: ...

    def evaluate_rules(
        self, bundle: NormalizedDataBundle, incident: Incident | None = None
    ) -> SensingResult: ...

    def plan_routes(self, request: RouteRequest) -> RoutePlan: ...

    def calculate_ete(self, incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate: ...

    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
    ) -> tuple[str, Notification | None]: ...

    def run_agent(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
    ) -> BedrockAdvisory: ...

    # [2026-07-28總架構師補充：回應Kiro審查] 原本這裡還有 parse_whatif(question)/
    # narrate_whatif(question, result_facts) 兩個方法，對應 m5-api-orchestrator-dashboard/
    # design.md 設想的「LLM解析→Python重算→LLM敘述」三段式 What-if 流程。但 W1 實際
    # 定案的設計（W1-whatif-agent/design.md）是 Strands Agent 用 @tool 機制，LLM 在
    # 一次 Agent 呼叫內部自己決定要不要 call `query_sop`/`simulate_scenario`，「解析
    # 參數」跟「敘述結果」都內含在同一次 Agent 對話裡，不是外部呼叫端分兩次呼叫 LLM。
    # 這兩個方法從沒被任何程式碼呼叫過——是兩個獨立撰寫的 spec 對同一件事給了不同
    # 實作方式，W1 那邊的設計後來居上且已經全面鷹架，這裡確認以 W1 的方式為準，
    # 移除這兩個未使用的 Protocol 方法，不要實作它們。


class StubGateway:
    """開發初期用假資料回傳，事件相關欄位取自 available_incidents 的三筆 ID。
    不讀 data/**（那是 M1 的權限）。每次呼叫都要在 Envelope warnings 留下
    "module_stub_in_use:<module>"。

    [2026-07-28總架構師補充：回應Kiro審查——固定用 ACC_001 黃金情境反推假資料，
    不要自己編一組跟黃金值對不上的數字，這樣 Stub 模式下手動測試也能對答案]：
        load_data()      → 只需含 ACC_001 這筆 incident 的最小 bundle 即可
        evaluate_rules() → SensingResult(traffic_level="A", rule_hits=[命中SOP-2的
                            RuleHit], as_of=incident.timestamp)
        plan_routes()    → RoutePlan(primary=RD_TPE_004, secondary=RD_TPE_005,
                            excluded=[RD_TPE_006, RD_TPE_008]的假RouteCandidate)
        calculate_ete()  → EteEstimate(minutes=90, recovery_at="2026-05-20 23:40",
                            formula="60 + max(0,(1.0-0.5)*60) = 90", base_clearance=60,
                            average_saturation=1.0) —— 這組數字就是黃金驗收值本身，
                            Stub 模式下也應該要能通過 tests/test_orchestrator.py 的
                            test_acc001_golden_regression_full_pipeline
        generate_report()→ 回傳固定字串 + Notification(zh="...", en=None)
        run_agent()      → BedrockAdvisory(text="...", sop_evidence=[至少一筆假SopEvidence])
    """

    # TODO(Kiro): 依上述固定值實作全部方法。


class LiveGateway:
    """接真實模組。缺失模組個別降級為 stub 方法（混合狀態合法）。"""

    # TODO(Kiro): import src.loaders/rules/routing/reporting/agent，缺一個就對應
    # 方法降級用 StubGateway 的實作。


def build_gateway() -> ModuleGateway:
    """兩段式選擇：USE_STUB_MODULES=true 時強制回傳 StubGateway；否則嘗試 import
    真實模組，import 失敗才個別降級（m5-api-orchestrator-dashboard/design.md 第2節）。
    """
    if os.getenv("USE_STUB_MODULES", "false").lower() == "true":
        return StubGateway()
    try:
        from src import agent, loaders, reporting, routing, rules  # noqa: F401

        return LiveGateway()
    except ImportError:
        return StubGateway()


GATEWAY: ModuleGateway | None = None
"""[2026-07-28總架構師補充：架構完整性修正] main.py 啟動時呼叫 build_gateway() 賦值。

原本搭鷹架時，本檔下面的 handle_trigger_batch/handle_incident/classify_incident
完全沒有用到 ModuleGateway——等於白定義了 StubGateway/LiveGateway 這套「開發期間
先用假資料、之後換真實模組不用改呼叫端」的機制，卻沒有任何函式真的透過它存取
M1-M4。這是屬於「架構圖上畫了依賴注入，程式碼裡沒接線」的典型落差，以下函式
一律呼叫 `GATEWAY.xxx()`，不直接 `from src.rules import evaluate_rules` 這樣繞過去。
"""


# ---------------------------------------------------------------------------
# A1：事件分類器（查表，零LLM。m5-api-orchestrator-dashboard/design.md Data Models節，
# 已加註：SOP-2真實觸發條件是狀態/嚴重度/路段前綴組合判斷，這裡的型別查表是刻意的
# Demo範圍簡化，只保證 live_incidents.json 三筆固定事件跑出正確黃金值）
# ---------------------------------------------------------------------------


def classify_incident(incident: Incident) -> dict:
    """回傳 {主因SOP, requires_rerouting, 受影響路段來源}。

    對照表（m5-api-orchestrator-dashboard/design.md）：
        Road_Collapse_Accident → SOP-2 → requires_rerouting=True
        Crowd_Surge_Injury     → SOP-3 → requires_rerouting=False（已對照SOP原文確認：
                                          捷運分流處置完全不涉及路段層級改道）
        Power_Failure          → SOP-5 → requires_rerouting=False（同上，人工指揮不需路網重規劃）
        其他                    → 無（僅warning）→ requires_rerouting=False

    純查表，不呼叫 GATEWAY——這是唯一不需要透過 Gateway 存取模組的函式，
    因為它不依賴 M1-M4 的任何運算結果，只依賴 incident 本身的欄位。
    """
    raise NotImplementedError("見 m5-api-orchestrator-dashboard/design.md Data Models 節")


# ---------------------------------------------------------------------------
# GlobalState（SPEC-O1 §3，[2026-07-28總架構師補充：回應Kiro審查] 原文件只給了
# 型別骨架沒給 IncidentRecord 的精確欄位，這裡補齊）
# ---------------------------------------------------------------------------


@dataclass
class IncidentRecord:
    """GlobalState.active_incidents 的 value 型別。"""

    trace_id: str
    incident: Incident
    decision_result: DecisionResult | None = None
    """七階段跑完（PUSH）後才有值；PLAN/EXECUTE 中間階段為 None。"""
    bundle_snapshot: NormalizedDataBundle | None = None
    """OPEN 當下的 as-of bundle 快照，供 What-if 分支重算時取用（見 simulate_scenario）。"""


@dataclass
class GlobalState:
    multilingual: bool = False
    active_incidents: dict[str, IncidentRecord] = field(default_factory=dict)
    """key=event_id。寫入：週期 PUSH 階段；移除：收到恢復訊號（Partial_Open等）。"""
    cycle_counter: int = 0
    """trace_id 流水號（行程內）。"""


_STATE = GlobalState()


# ---------------------------------------------------------------------------
# A2：編排（折衷制——規則觸發=靜態分派表，事件注入=LLM規劃器+降級保底）
# ---------------------------------------------------------------------------


def handle_trigger_batch(batch: list[dict]) -> DecisionResult:
    """規則引擎呼叫入口。批次空陣列拋 ValueError（fail fast）。

    [2026-07-28總架構師補充：回應Kiro審查——這個函式的呼叫端]這是唯一一個
    API表面上沒有對應REST端點的入口，因為它的觸發來源是「規則引擎每個tick產出
    的TriggeredRule[]」（SPEC-O1表格），不是使用者操作。呼叫端是 `main.py` 啟動時
    註冊的一個背景排程任務（FastAPI `@app.on_event("startup")` 或 `asyncio.create_task`），
    定期（demo資料時間跨度短，建議每次啟動時跑一次全量評估即可，不需要真的每15分鐘
    輪詢；如果要做成真的定時器，週期抓 `.kiro/steering/00-tech-stack.md`
    沒有規定，可以設一個常數，如 60 秒方便demo時展示效果）呼叫 `GATEWAY.evaluate_rules()`
    掃全部15路段，比對上一次結果找出新的 rule_hits（尤其 B/A 級轉換），組成
    TriggeredRule[] 傳進來。這個排程任務屬於 Phase 9（main.py），不是這個函式自己
    要處理「誰呼叫我」，但補在這裡讓實作時知道不用等一個不存在的REST端點。

    TODO(Kiro): 依 SPEC-O2 §2 靜態分派表實作 §1-§6 各條規則對應的任務鏈；
    §4 自動連動§3、[§1-A,§4]合併等細節見 SPEC-O2 §2.1/2.2。
    全部對 M1/M2/M4 的存取一律經由 `GATEWAY`（例如 `GATEWAY.evaluate_rules(...)`），
    不要 `from src.rules import evaluate_rules` 直接繞過去——不然 StubGateway/
    LiveGateway 的切換機制就形同虛設，M5 也沒辦法在其他模組還沒完成前先用假資料開發。
    """
    if batch is not None and len(batch) == 0:
        raise ValueError("batch 不得為空陣列")
    raise NotImplementedError("見 SPEC-O1 + SPEC-O2")


def handle_incident(event: Incident) -> DecisionResult:
    """D4 監聽器呼叫入口，對應 REST POST /api/incidents/evaluate 之後端
    （[2026-07-28更正] SPEC-O3 原寫 /api/inject，已改為固定端點名）。
    event_id / affected_segment 缺漏拋 ValueError。

    TODO(Kiro): 依 SPEC-O1 七階段生命週期（OPEN→FLAGS→PLAN→EXECUTE→SUMMARY→
    EXPLAIN→PUSH）+ SPEC-O2 §3 事件注入流程（LLM規劃器，三層護欄，失敗降級靜態鏈）實作。
    同上，全部經由 `GATEWAY` 存取，不直接 import M1/M2/M4 的模組。

    OPEN 階段建立 `IncidentRecord(trace_id, incident=event, bundle_snapshot=GATEWAY.load_data())`
    寫入 `_STATE.active_incidents[event.event_id]`；PUSH 階段補上 `decision_result`。
    這是 Kiro 審查抓到的 `_get_current_context()` 缺口的另一半——W1 simulate_scenario
    透過 `_current_trace_ctx`（見下方 `handle_user_query`）取得 trace_id 後，
    從這裡的 `_STATE.active_incidents` 查對應的 incident/bundle_snapshot。
    """
    if not event.event_id or not event.affected_segment:
        raise ValueError("event_id / affected_segment 缺漏")
    raise NotImplementedError("見 SPEC-O1 + SPEC-O2")


_FORWARD_LOOKING_WORDS = ("如果", "假設", "若", "會怎樣", "怎麼辦")
"""SPEC-O3 §4：問題含任一詞即走前瞻假設分支，優先序高於回溯追問。"""

_current_trace_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_trace_id", default=None
)
"""[2026-07-28總架構師補充：回應Kiro審查——解決 _get_current_context() 缺口]

Strands `@tool` 裝飾的函式（`agent/tools.py` 的 `simulate_scenario`）是被 LLM
呼叫、參數由 LLM 決定，沒辦法讓呼叫端顯式傳入 trace_id/session_id 這種請求範疇的
上下文。標準做法是用 `contextvars.ContextVar` 在請求進來時（這裡）設定一次，
工具函式內部讀取，不需要改 LLM 的 tool-calling 介面。`handle_user_query()` 收到
`current_trace_id` 後在呼叫 W1 之前先設定這個變數；`simulate_scenario` 讀
`_current_trace_ctx.get()` 拿到 trace_id 後查 `_STATE.active_incidents[?]`
（用 trace_id 找對應 event_id 需要一次反查，或乾脆讓 IncidentRecord 用 trace_id
當 key——這個選擇留給 Kiro 實作時二選一，兩者都合理，不影響其他介面）。

若 `current_trace_id` 為 None（使用者沒有正在查看特定事件、但問題仍含前瞻假設詞），
`simulate_scenario` 應該只能做「不依賴特定事件」的模擬（例如只重算 `evaluate_rules`
不含 `incident`，略過需要 incident 的路網/ETE 部分），這是合理的功能邊界，不是bug。
"""


def handle_user_query(question: str, current_trace_id: str | None, session_id: str, correlation_id: str) -> dict:
    """前端對話入口，對應 REST POST /api/what-if（[2026-07-28更正] SPEC-O3 原寫
    /api/chat，已改為固定端點名）。

    三分支路由（確定性、零LLM，SPEC-O3 §4，優先序：前瞻詞優先於回溯）。
    """
    from src.agent.whatif_agent import process_whatif_request
    from src.decision_trace import answer_trace_query

    if any(word in question for word in _FORWARD_LOOKING_WORDS):
        _current_trace_ctx.set(current_trace_id)
        result = process_whatif_request(session_id=session_id, content=question)
        return {"message_type": "whatif.evaluated.v1", "payload": result}

    if current_trace_id is not None:
        answer_text = answer_trace_query(current_trace_id, question)
        return {
            "message_type": "trace.answered.v1",
            "payload": {"trace_id": current_trace_id, "answer_text": answer_text},
        }

    return {
        "message_type": "trace.answered.v1",
        "payload": {
            "trace_id": None,
            "answer_text": "目前無進行中的決策週期可查詢。若要詢問假設情境，請以『如果…』開頭。",
        },
    }


def get_global_state() -> GlobalState:
    """測試與 demo 重播輔助。[2026-07-28總架構師補充] 直接回傳 `_STATE`
    （已定義為模組層級的 `GlobalState` dataclass，見本檔上方），不是空字典。
    """
    return _STATE


def reset() -> None:
    """測試與 demo 重播輔助：清空 `_STATE`，回到跟行程剛啟動時一樣的狀態。"""
    global _STATE
    _STATE = GlobalState()
