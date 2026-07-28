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

import os
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
    ScenarioOverrides,
    SensingResult,
    WhatIfResult,
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

    def parse_whatif(self, question: str) -> ScenarioOverrides: ...

    def narrate_whatif(self, question: str, result_facts: WhatIfResult) -> tuple[str, list]: ...


class StubGateway:
    """開發初期用假資料回傳，事件相關欄位取自 available_incidents 的三筆 ID。
    不讀 data/**（那是 M1 的權限）。每次呼叫都要在 Envelope warnings 留下
    "module_stub_in_use:<module>"。
    """

    # TODO(Kiro): 依 m5-api-orchestrator-dashboard/design.md 第2節實作全部方法。


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
# A2：編排（折衷制——規則觸發=靜態分派表，事件注入=LLM規劃器+降級保底）
# ---------------------------------------------------------------------------


def handle_trigger_batch(batch: list[dict]) -> DecisionResult:
    """規則引擎呼叫入口。批次空陣列拋 ValueError（fail fast）。

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
    """
    if not event.event_id or not event.affected_segment:
        raise ValueError("event_id / affected_segment 缺漏")
    raise NotImplementedError("見 SPEC-O1 + SPEC-O2")


_FORWARD_LOOKING_WORDS = ("如果", "假設", "若", "會怎樣", "怎麼辦")
"""SPEC-O3 §4：問題含任一詞即走前瞻假設分支，優先序高於回溯追問。"""


def handle_user_query(question: str, current_trace_id: str | None, session_id: str, correlation_id: str) -> dict:
    """前端對話入口，對應 REST POST /api/what-if（[2026-07-28更正] SPEC-O3 原寫
    /api/chat，已改為固定端點名）。

    三分支路由（確定性、零LLM，SPEC-O3 §4，優先序：前瞻詞優先於回溯）。
    """
    from src.agent.whatif_agent import process_whatif_request
    from src.decision_trace import answer_trace_query

    if any(word in question for word in _FORWARD_LOOKING_WORDS):
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


def get_global_state() -> dict:
    """測試與 demo 重播輔助。"""
    raise NotImplementedError("見 SPEC-O1 §3 GlobalState")


def reset() -> None:
    """測試與 demo 重播輔助。"""
    raise NotImplementedError("見 SPEC-O1 §3 GlobalState")
