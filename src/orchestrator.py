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
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)
_TZ_TAIPEI = timezone(timedelta(hours=8))

from src.models import (
    BedrockAdvisory,
    DecisionResult,
    EteEstimate,
    EvidenceRef,
    Incident,
    IncidentSeverity,
    Notification,
    NormalizedDataBundle,
    RouteCandidate,
    RoutePlan,
    RouteRequest,
    RuleHit,
    SensingResult,
    SopEvidence,
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

    # [2026-07-28架構複查新增] `bundle` 參數：回應SPEC-O2「§5必含COUNT_INTERSECTIONS」——
    # SOP-5（號誌故障）需要用路網拓樸算受影響路口數（`routing.count_affected_intersections()`），
    # 警力人數=路口數×2，這個計算需要 bundle 才能做，之前完全沒傳進來，是 §5 這條 SOP 的
    # 人力派遣建議一直缺少具體人數的原因。
    # [2026-08-01新增] `merged_incident_info` 參數：同路段多事件合併報告書所需資訊。
    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
        bundle: NormalizedDataBundle,
        merged_incident_info: dict | None = None,
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
    """開發初期用假資料回傳，固定用 ACC_001 黃金值反推。"""

    def load_data(self) -> NormalizedDataBundle:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=8))
        now = datetime(2026, 5, 20, 22, 10, tzinfo=tz)
        return NormalizedDataBundle(
            traffic=[],
            crowd=[],
            road_network=[],
            incidents=[
                Incident(
                    event_id="TPE_2026_ACC_001",
                    type="Road_Collapse_Accident",
                    location="光復南路/忠孝東路口",
                    affected_segment="RD_TPE_002",
                    status="Closed",
                    severity=IncidentSeverity.CRITICAL,
                    description="路面塌陷",
                    timestamp=now,
                ),
            ],
            sop=[],
            loaded_at=now,
        )

    def evaluate_rules(
        self, bundle: NormalizedDataBundle, incident: Incident | None = None
    ) -> SensingResult:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=8))
        as_of = incident.timestamp if incident else datetime(2026, 5, 20, 22, 10, tzinfo=tz)
        return SensingResult(
            traffic_level="A",
            rule_hits=[
                RuleHit(
                    clause_id="SOP-2",
                    segment_id="RD_TPE_002",
                    evidence=EvidenceRef(field="status+severity", value="Closed/Critical", threshold="Closed|Blocked|Restricted + High|Critical"),
                    is_primary=True,
                ),
                RuleHit(
                    clause_id="SOP-1",
                    segment_id="RD_TPE_002",
                    evidence=EvidenceRef(field="saturation_score", value=1.0, threshold=0.95),
                    city_response=True,
                ),
            ],
            as_of=as_of,
            multilingual_required=True,
        )

    def plan_routes(self, request: RouteRequest) -> RoutePlan:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=8))
        snap = datetime(2026, 5, 20, 22, 0, tzinfo=tz)
        return RoutePlan(
            primary=RouteCandidate(
                segment_id="RD_TPE_004", name="市民大道四段", eligible=True,
                reason_code=None, saturation_score=0.78, capacity_vph=2500, snapshot_at=snap,
            ),
            secondary=RouteCandidate(
                segment_id="RD_TPE_005", name="仁愛路四段", eligible=True,
                reason_code=None, saturation_score=0.65, capacity_vph=4000, snapshot_at=snap,
            ),
            excluded=[
                RouteCandidate(
                    segment_id="RD_TPE_006", name="敦化南路一段", eligible=False,
                    reason_code="NOT_DIRECTLY_INTERSECTING", saturation_score=0.72,
                    capacity_vph=3200, snapshot_at=snap,
                ),
                RouteCandidate(
                    segment_id="RD_TPE_008", name="延吉街", eligible=False,
                    reason_code="CAPACITY_INSUFFICIENT", saturation_score=0.8,
                    capacity_vph=600, snapshot_at=snap,
                ),
            ],
            findings=[],
            candidates=[],
            no_feasible_route=False,
            duration_ms=5,
            within_60_second_sla=True,
        )

    def calculate_ete(self, incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate:
        return EteEstimate(
            minutes=90,
            recovery_at="2026-05-20 23:40",
            formula="60 + max(0,(1.0-0.5)*60) = 90",
            base_clearance=60,
            average_saturation=1.0,
        )

    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
        bundle: NormalizedDataBundle,
        merged_incident_info: dict | None = None,
    ) -> tuple[str, Notification | None]:
        report = (
            f"【交控建議書】事件 {incident.event_id}\n"
            f"[STUB] 建議改道市民大道四段，預計 {ete.minutes} 分鐘恢復。"
        )
        notification = Notification(zh=f"[STUB] {incident.location}發生事故，建議改道。")
        return report, notification

    def run_agent(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
    ) -> BedrockAdvisory:
        return BedrockAdvisory(
            text="[STUB] 根據 SOP-2，建議啟動替代路線引導。",
            sop_evidence=[SopEvidence(section_number=2, title="車禍與路障應變", content="[STUB]", relevance_score=0.9)],
        )


class LiveGateway:
    """接真實模組。缺失模組個別降級為 StubGateway 對應方法（混合狀態合法）。"""

    def __init__(self):
        self._stub = StubGateway()

    def load_data(self) -> NormalizedDataBundle:
        from src.loaders import load_data
        return load_data()

    def evaluate_rules(
        self, bundle: NormalizedDataBundle, incident: Incident | None = None
    ) -> SensingResult:
        from src.rules import evaluate_rules
        return evaluate_rules(bundle, incident)

    def plan_routes(self, request: RouteRequest) -> RoutePlan:
        from src.routing import plan_route
        return plan_route(request)

    def calculate_ete(self, incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate:
        from src.reporting import calculate_ete
        return calculate_ete(incident, bundle)

    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
        bundle: NormalizedDataBundle,
        merged_incident_info: dict | None = None,
    ) -> tuple[str, Notification | None]:
        from src.reporting import generate_report
        return generate_report(incident, sensing, route_plan, ete, advisory, bundle, merged_incident_info)

    def run_agent(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
    ) -> BedrockAdvisory:
        """呼叫 W1 Agent 取得 SOP 建議。失敗時降級回 StubGateway 的假回傳。"""
        try:
            from src.agent.whatif_agent import process_whatif
            from src.session.models import W1Context

            # 組一個簡單的 context 讓 Agent 產出建議
            context = W1Context(
                session_id="__orchestrator__",
                new_message=f"事件 {incident.event_id} 發生在 {incident.location}，請提供 SOP 建議",
                history=[],
                accumulated_assumptions={},
            )
            response = process_whatif(context)
            # 從 W1Response 轉成 BedrockAdvisory
            from src.models import SopEvidence
            sop_evidence = [
                SopEvidence(
                    section_number=s.get("section_number", 0),
                    title=s.get("title", ""),
                    content=s.get("content", ""),
                    relevance_score=s.get("relevance_score", 0.5),
                )
                for s in response.triggered_sops
            ] if response.triggered_sops else [
                SopEvidence(section_number=0, title="N/A", content="Agent 未回傳 SOP 依據", relevance_score=0.0)
            ]
            return BedrockAdvisory(
                text=response.summary,
                sop_evidence=sop_evidence,
            )
        except Exception:
            return self._stub.run_agent(incident, sensing, route_plan, ete)


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
    """回傳 {primary_sop, requires_rerouting, affected_source}。

    對照表（m5-api-orchestrator-dashboard/design.md + 擴充）：
        Road_Collapse_Accident → SOP-2 → requires_rerouting=True   # 路面塌陷
        Traffic_Accident       → SOP-2 → requires_rerouting=True   # 一般車禍
        Vehicle_Fire           → SOP-2 → requires_rerouting=True   # 車輛火警
        Crowd_Surge_Injury     → SOP-3 → requires_rerouting=False  # 人群推擠
        Large_Event_Dispersal  → SOP-4 → requires_rerouting=False  # 大型活動散場
        Power_Failure          → SOP-5 → requires_rerouting=False  # 號誌故障
        Water_Main_Break       → SOP-2 → requires_rerouting=False  # 水管破裂（減速即可）
        Debris_On_Road         → SOP-2 → requires_rerouting=False  # 路面掉落物（清除快）
        其他                    → None  → requires_rerouting=False

    requires_rerouting 判定邏輯：
    - True：事件會導致道路完全或大部分封閉，車流需要改道
    - False：事件影響局部或短暫，減速/管制即可，不需大規模改道
    
    [2026-07-28擴充] 額外考慮 status + severity 組合：
    - status=Closed + severity=Critical/High → 強制 requires_rerouting=True
    """
    type_map = {
        # 需要路網重規劃的嚴重事件
        "Road_Collapse_Accident": ("SOP-2", True),
        "Traffic_Accident": ("SOP-2", True),
        "Vehicle_Fire": ("SOP-2", True),
        # 人流相關（不需道路改道）
        "Crowd_Surge_Injury": ("SOP-3", False),
        "Large_Event_Dispersal": ("SOP-4", False),
        # 設備/環境問題
        "Power_Failure": ("SOP-5", False),
        "Water_Main_Break": ("SOP-2", False),
        "Debris_On_Road": ("SOP-2", False),
    }

    primary_sop, requires_rerouting = type_map.get(incident.type, (None, False))

    # 受影響路段來源：affected_road 優先，否則 affected_segment
    affected_source = incident.affected_road or incident.affected_segment

    return {
        "primary_sop": primary_sop,
        "requires_rerouting": requires_rerouting,
        "affected_source": affected_source,
    }


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
    sensing_result: SensingResult | None = None
    """初次評估時的規則命中結果，供路線重規劃時重新生成報告書使用。"""
    route_replan_count: int = 0
    """該事件的路線重規劃次數。"""
    last_route_check_at: datetime | None = None
    """上次檢查路線有效性的時間。"""


@dataclass
class GlobalState:
    multilingual: bool = False
    active_incidents: dict[str, IncidentRecord] = field(default_factory=dict)
    """key=event_id。寫入：週期 PUSH 階段；移除：收到恢復訊號（Partial_Open等）。"""
    cycle_counter: int = 0
    """trace_id 流水號（行程內）。"""
    resolved_incidents: dict[str, IncidentRecord] = field(default_factory=dict)
    """已解除事件的歷史紀錄，供 Dashboard 顯示。"""


_STATE = GlobalState()


# ---------------------------------------------------------------------------
# 情境1：同路段多事件合併 ETE 計算
# ---------------------------------------------------------------------------

_MULTI_INCIDENT_DELAY_MINUTES = 15
"""每多一個同路段事件，增加的協調延遲（分鐘）。"""


def get_same_segment_incidents(segment_id: str, exclude_event_id: str | None = None) -> list[IncidentRecord]:
    """取得同一路段的所有活躍事件。"""
    result = []
    for event_id, record in _STATE.active_incidents.items():
        if exclude_event_id and event_id == exclude_event_id:
            continue
        affected = record.incident.affected_road or record.incident.affected_segment
        if affected == segment_id:
            result.append(record)
    return result


def calculate_merged_ete(base_ete_minutes: int, same_segment_count: int) -> int:
    """情境1：合併 ETE 計算。
    
    公式：合併 ETE = max(各事件ETE) + (事件數量 - 1) × 15分鐘
    
    Args:
        base_ete_minutes: 基礎 ETE（最大值）
        same_segment_count: 同路段事件總數（含自己）
    
    Returns:
        合併後的 ETE 分鐘數
    """
    if same_segment_count <= 1:
        return base_ete_minutes
    
    delay = (same_segment_count - 1) * _MULTI_INCIDENT_DELAY_MINUTES
    return base_ete_minutes + delay


def get_merged_incident_info(segment_id: str) -> dict | None:
    """取得同路段事件的合併資訊。
    
    Returns:
        {
            "event_ids": [...],
            "count": int,
            "max_ete_minutes": int,
            "merged_ete_minutes": int,
            "descriptions": [...],
        }
        如果該路段只有一個事件或沒有事件，回傳 None。
    """
    incidents = get_same_segment_incidents(segment_id)
    if len(incidents) <= 1:
        return None
    
    event_ids = []
    descriptions = []
    max_ete = 0
    
    for record in incidents:
        event_ids.append(record.incident.event_id)
        descriptions.append(record.incident.description)
        if record.decision_result and record.decision_result.ete:
            ete = record.decision_result.ete.minutes
            if ete > max_ete:
                max_ete = ete
    
    merged_ete = calculate_merged_ete(max_ete, len(incidents))
    
    return {
        "event_ids": event_ids,
        "count": len(incidents),
        "max_ete_minutes": max_ete,
        "merged_ete_minutes": merged_ete,
        "descriptions": descriptions,
    }


# ---------------------------------------------------------------------------
# A2：編排（折衷制——規則觸發=靜態分派表，事件注入=LLM規劃器+降級保底）
# ---------------------------------------------------------------------------


def handle_trigger_batch(batch: list[dict]) -> DecisionResult:
    """規則引擎呼叫入口。批次空陣列拋 ValueError（fail fast）。

    靜態分派表（SPEC-O2 §2）：依規則觸發對應的任務鏈產出 DecisionResult。
    呼叫端是 main.py 啟動時註冊的背景排程任務（Phase 9）。
    """
    if batch is not None and len(batch) == 0:
        raise ValueError("batch 不得為空陣列")

    import time
    start = time.perf_counter()

    # 載入資料
    bundle = GATEWAY.load_data()

    # 評估規則（無特定 incident）
    sensing = GATEWAY.evaluate_rules(bundle, incident=None)

    # 產生 trace_id
    _STATE.cycle_counter += 1
    trace_id = f"TR-{datetime.now(_TZ_TAIPEI).strftime('%Y%m%d-%H%M')}-{_STATE.cycle_counter:04d}"

    # 開啟 trace
    from src.decision_trace import open_trace, record_step
    triggered_by = [f"§{b.get('section', '?')}" for b in batch if b.get('section')]
    if not triggered_by:
        triggered_by = ["§1"]
    try:
        open_trace(trace_id, triggered_by)
    except ValueError:
        pass  # trace 已存在（重入保護）

    # 記錄 PLAN 步驟
    try:
        record_step(trace_id, "A2", "PLAN", {"batch": batch}, {"static_dispatch": True})
    except Exception as e:
        logger.warning(f"record_step 寫入失敗: {e}")

    # 組裝 DecisionResult
    elapsed = int((time.perf_counter() - start) * 1000)

    # 判斷 is_simulated
    # [2026-07-28架構複查修正：回應SPEC-O3對照表第8項] 原本只檢查 bundle.traffic，
    # 但 SPEC-O3 明訂「只要有任一 provenance=demo 的欄位被使用才為 true」，bundle.crowd
    # 也有獨立的 provenance 欄位（CrowdSample.provenance），必須一併檢查，否則人流資料
    # 若曾經退化成 demo/derived，這裡會誤判為 false。
    from src.models import DataProvenance
    is_simulated = (
        any(t.provenance != DataProvenance.PROVIDED for t in bundle.traffic)
        or any(c.provenance != DataProvenance.PROVIDED for c in bundle.crowd)
    )

    return DecisionResult(
        trace_id=trace_id,
        triggered_by=triggered_by,
        level=sensing.traffic_level if sensing.traffic_level != "normal" else None,
        incident=None,
        routes=None,
        ete=None,
        control_center_report=None,
        notifications=None,
        degraded=[],
        duration_ms=elapsed,
        is_simulated=is_simulated,
    )


async def _broadcast_task_update(
    ws_broadcaster,
    trace_id: str,
    dispatch_seq: int,
    status: str,
) -> None:
    """直接 await 推播 decision.task_update.v1，確保即時送出。"""
    if ws_broadcaster is None:
        return
    try:
        await ws_broadcaster({
            "message_type": "decision.task_update.v1",
            "payload": {
                "trace_id": trace_id,
                "dispatch_seq": dispatch_seq,
                "status": status,
            },
        })
    except Exception:
        pass  # 推播失敗不影響主流程


async def handle_incident(event: Incident, ws_broadcaster=None) -> DecisionResult:
    """D4 監聽器呼叫入口，對應 REST POST /api/incidents/evaluate。

    七階段生命週期：OPEN→FLAGS→PLAN→EXECUTE→SUMMARY→EXPLAIN→PUSH。

    ws_broadcaster: 可選 async function，用於推播 decision.task_update.v1
    讓前端 Agent 活動面板即時顯示每一步的進度。
    """
    if not event.event_id or not event.affected_segment:
        raise ValueError("event_id / affected_segment 缺漏")

    import time
    start = time.perf_counter()

    from src.decision_trace import open_trace, record_step

    # --- 1. OPEN ---
    _STATE.cycle_counter += 1
    trace_id = f"TR-{datetime.now(_TZ_TAIPEI).strftime('%Y%m%d-%H%M')}-{_STATE.cycle_counter:04d}"

    # A1 分類
    classification = classify_incident(event)
    triggered_by_list = []
    if classification["primary_sop"]:
        triggered_by_list.append(f"§{classification['primary_sop'].split('-')[1]}")
    if not triggered_by_list:
        triggered_by_list = ["§1"]

    try:
        open_trace(trace_id, triggered_by_list)
    except ValueError as e:
        logger.warning(f"open_trace 失敗: {e}")

    # 載入 bundle 並快照（7.4 _get_current_context 的前提）
    bundle = GATEWAY.load_data()
    _STATE.active_incidents[event.event_id] = IncidentRecord(
        trace_id=trace_id,
        incident=event,
        bundle_snapshot=bundle,
        sensing_result=None,  # 稍後由 evaluate_rules 填入
    )

    # --- 2. FLAGS ---
    sensing = GATEWAY.evaluate_rules(bundle, event)
    if sensing.multilingual_required:
        _STATE.multilingual = True
    
    # 保存 sensing_result 供路線重規劃時重新生成報告書使用
    record = _STATE.active_incidents.get(event.event_id)
    if record:
        record.sensing_result = sensing
    
    try:
        record_step(trace_id, "A2", "SET_FLAG", {"multilingual": _STATE.multilingual}, {})
    except Exception as e:
        logger.warning(f"record_step SET_FLAG 失敗: {e}")

    # --- 3. PLAN ---
    requires_rerouting = classification["requires_rerouting"]
    try:
        record_step(trace_id, "A2", "PLAN", {
            "event_id": event.event_id,
            "classification": classification,
            "requires_rerouting": requires_rerouting,
        }, {"static_dispatch": True})
    except Exception as e:
        logger.warning(f"record_step PLAN 失敗: {e}")

    # --- 4. EXECUTE ---
    route_plan: RoutePlan | None = None
    ete: EteEstimate | None = None
    report_text: str | None = None
    notification: Notification | None = None
    degraded: list[str] = []
    _dispatch_seq = 0

    # 嘗試 A2 LLM 規劃器（SPEC-O2 §3），失敗時安全網接手
    from src.agent.a2_orchestrator_agent import decide_and_execute
    a2_result = decide_and_execute(
        event_id=event.event_id,
        event_type=event.type,
        classification=classification,
    )

    if a2_result is not None:
        # A2 Agent 成功——tool 內部已經真的呼叫過 GATEWAY 方法，
        # 結果以 dict 存在 a2_result 裡。重建 Pydantic 物件：
        if a2_result.get("route_plan") and requires_rerouting:
            _dispatch_seq += 1
            await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_started")
            try:
                route_plan = GATEWAY.plan_routes(
                    RouteRequest(incident=event, bundle=bundle, as_of=event.timestamp)
                )
            except Exception as e:
                logger.warning(f"A2 指示 plan_routes 但執行失敗: {e}")
            _dispatch_seq += 1
            await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_done")

        if a2_result.get("ete"):
            _dispatch_seq += 1
            await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_started")
            try:
                ete = GATEWAY.calculate_ete(event, bundle)
            except Exception as e:
                logger.warning(f"A2 指示 calculate_ete 但執行失敗: {e}")
            _dispatch_seq += 1
            await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_done")

        logger.info(f"A2 Agent 規劃完成（planned_by={a2_result.get('planned_by')}）")

    # 安全網：Agent 漏呼叫必要工具、或 Agent 不可用時，確定性模組補位
    if requires_rerouting and route_plan is None:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_started")
        try:
            route_plan = GATEWAY.plan_routes(
                RouteRequest(incident=event, bundle=bundle, as_of=event.timestamp)
            )
        except Exception as e:
            logger.warning(f"plan_routes 失敗: {e}")
            degraded.append("ROUTING_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_done")

    # ETE（所有事件必須有）
    if ete is None:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_started")
        try:
            ete = GATEWAY.calculate_ete(event, bundle)
        except Exception as e:
            logger.warning(f"calculate_ete 失敗: {e}")
            degraded.append("ETE_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_done")

    # ★ 情境1：同路段多事件合併 ETE
    affected_seg = event.affected_road or event.affected_segment
    same_segment_incidents = get_same_segment_incidents(affected_seg, exclude_event_id=event.event_id)
    merged_incident_info = None
    
    if same_segment_incidents and ete is not None:
        # 有其他同路段事件，需要計算合併 ETE
        # 找出所有同路段事件中最大的 ETE
        all_etes = [ete.minutes]
        for other_record in same_segment_incidents:
            if other_record.decision_result and other_record.decision_result.ete:
                all_etes.append(other_record.decision_result.ete.minutes)
        
        max_ete = max(all_etes)
        total_count = len(same_segment_incidents) + 1  # 包含自己
        merged_ete = calculate_merged_ete(max_ete, total_count)
        
        logger.info(f"[同路段事件合併] {event.event_id} 與 {len(same_segment_incidents)} 個事件同路段，"
                    f"原始 ETE={ete.minutes}，最大 ETE={max_ete}，合併後={merged_ete} 分鐘")
        
        # 更新 ETE
        ete = EteEstimate(
            minutes=merged_ete,
            recovery_at=ete.recovery_at,  # 暫時保持原值，之後可以重算
            formula=f"{ete.formula} → 合併計算: max({max_ete}) + ({total_count}-1)×15 = {merged_ete}",
            base_clearance=ete.base_clearance,
            average_saturation=ete.average_saturation,
        )
        
        # 記錄合併資訊
        merged_incident_info = {
            "event_ids": [event.event_id] + [r.incident.event_id for r in same_segment_incidents],
            "count": total_count,
            "max_ete_minutes": max_ete,
            "merged_ete_minutes": merged_ete,
            "descriptions": [event.description] + [r.incident.description for r in same_segment_incidents],
        }

    # Agent 建議
    advisory: BedrockAdvisory | None = None
    try:
        advisory = GATEWAY.run_agent(event, sensing, route_plan, ete)
    except Exception as e:
        logger.warning(f"run_agent 失敗: {e}")

    # 報告生成
    if ete is not None:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "report_started")
        try:
            report_text, notification = GATEWAY.generate_report(event, sensing, route_plan, ete, advisory, bundle, merged_incident_info)
        except Exception as e:
            logger.warning(f"generate_report 失敗: {e}")
        if report_text is None:
            degraded.append("C1_FAILED")
        if notification is None and _STATE.multilingual:
            degraded.append("C4_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "report_done")

    # --- 5. SUMMARY ---
    elapsed = int((time.perf_counter() - start) * 1000)
    try:
        record_step(trace_id, "A2", "CYCLE_SUMMARY", {},
                    {"duration_ms": elapsed},
                    subject_segment_ids=[event.affected_segment] if event.affected_segment.startswith("RD_") else [])
    except Exception as e:
        logger.warning(f"record_step CYCLE_SUMMARY 失敗: {e}")

    # --- 6. EXPLAIN ---
    try:
        from src.decision_trace import generate_report_explanation
        generate_report_explanation(trace_id)
    except Exception as e:
        logger.warning(f"generate_report_explanation 失敗（降級）: {e}")

    # --- 7. PUSH ---
    # [2026-07-28架構複查修正：回應SPEC-O3對照表第8項，同 handle_trigger_batch() 的修正]
    from src.models import DataProvenance
    is_simulated = (
        any(t.provenance != DataProvenance.PROVIDED for t in bundle.traffic)
        or any(c.provenance != DataProvenance.PROVIDED for c in bundle.crowd)
    )

    decision_result = DecisionResult(
        trace_id=trace_id,
        triggered_by=triggered_by_list,
        level=sensing.traffic_level if sensing.traffic_level != "normal" else None,
        incident=event,
        routes=route_plan,
        ete=ete,
        control_center_report=report_text,
        notifications=notification,
        degraded=degraded,
        duration_ms=elapsed,
        is_simulated=is_simulated,
        merged_incident_info=merged_incident_info,
    )

    # 更新 GlobalState
    record = _STATE.active_incidents.get(event.event_id)
    if record:
        record.decision_result = decision_result

    return decision_result


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


def handle_user_query(
    question: str,
    current_trace_id: str | None,
    session_id: str,
    correlation_id: str,
    ws_broadcaster=None,
) -> dict:
    """前端對話入口，對應 REST POST /api/what-if（[2026-07-28更正] SPEC-O3 原寫
    /api/chat，已改為固定端點名）。

    三分支路由（確定性、零LLM，SPEC-O3 §4，優先序：前瞻詞優先於回溯）。

    [2026-07-28架構複查修正：回應2026-07-28_架構圖合規性複查與待辦.md §2.2]
    `ws_broadcaster` 原本沒有這個參數，導致 `agent/loading.py` 的
    `chat.loading_start.v1`/`chat.loading_step.v1` 推播雖然兩端都寫好，
    中間卻永遠斷開（`main.py` 沒有東西可以傳進來）。現在補上參數並轉傳給
    `process_whatif_request()`（該函式本來就有 `ws_broadcaster` 參數，只是
    沒人傳），呼叫端見 `main.py::what_if()`。
    """
    from src.agent.whatif_agent import process_whatif_request
    from src.decision_trace import answer_trace_query

    if any(word in question for word in _FORWARD_LOOKING_WORDS):
        _current_trace_ctx.set(current_trace_id)
        result = process_whatif_request(session_id=session_id, content=question, correlation_id=correlation_id, ws_broadcaster=ws_broadcaster)
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
    # 同時清空 decision_trace 的所有紀錄
    from src.decision_trace import reset_traces
    reset_traces()


# ---------------------------------------------------------------------------
# 路線有效性監測與重規劃（背景週期性呼叫）
# ---------------------------------------------------------------------------


@dataclass
class RouteMonitorResult:
    """check_and_replan_routes() 的回傳結果。"""
    event_id: str
    replanned: bool
    """True 表示有執行重規劃。"""
    old_primary: str | None
    new_primary: str | None
    old_secondary: str | None
    new_secondary: str | None
    invalid_reasons: dict[str, str]
    """失效原因，key=segment_id。"""
    new_decision_result: DecisionResult | None = None
    """重規劃後的新 DecisionResult。"""


def check_and_replan_routes(
    event_id: str,
    as_of: datetime,
) -> RouteMonitorResult | None:
    """檢查指定事件的推薦路線是否仍有效，失效則重新規劃。

    此函式由背景監測迴圈呼叫，純確定性邏輯（只呼叫 routing/rules，不呼叫 LLM）。
    回傳 None 表示該 event_id 不存在於 active_incidents 或尚無 decision_result。
    """
    record = _STATE.active_incidents.get(event_id)
    if record is None or record.decision_result is None:
        return None

    old_routes = record.decision_result.routes
    if old_routes is None:
        # 此事件本來就不需要路網規劃（例如 SOP-3/5）
        return None

    # 取得當前 bundle（非快照，用即時資料檢查飽和度）
    bundle = GATEWAY.load_data()

    # 收集目前所有封閉路段（來自 active_incidents）
    closed_segments: set[str] = set()
    for r in _STATE.active_incidents.values():
        inc = r.incident
        if inc.status in ("Closed", "Blocked"):
            if inc.affected_segment:
                closed_segments.add(inc.affected_segment)
            if inc.affected_road:
                closed_segments.add(inc.affected_road)

    # 呼叫 routing.check_route_validity
    from src.routing import check_route_validity
    validity = check_route_validity(old_routes, bundle, as_of, closed_segments)

    # 更新上次檢查時間
    record.last_route_check_at = as_of

    if not validity.needs_replan:
        return RouteMonitorResult(
            event_id=event_id,
            replanned=False,
            old_primary=old_routes.primary.segment_id if old_routes.primary else None,
            new_primary=None,
            old_secondary=old_routes.secondary.segment_id if old_routes.secondary else None,
            new_secondary=None,
            invalid_reasons={},
        )

    # 需要重規劃
    logger.info(f"[路線監測] {event_id} 路線失效，原因: {validity.invalid_reasons}，執行重規劃")

    # 重新規劃路線
    new_route_plan = GATEWAY.plan_routes(
        RouteRequest(incident=record.incident, bundle=bundle, as_of=as_of)
    )

    # 更新 decision_result 的 routes 以及重新生成報告書與簡訊
    old_decision = record.decision_result
    
    # 重新生成報告書與簡訊（路線改了，報告內容也要同步更新）
    # 需要 sensing 資訊，從原 decision 取用（sensing 在初次評估時已存入 record）
    new_report = old_decision.control_center_report
    new_notification = old_decision.notifications
    degraded = list(old_decision.degraded)
    
    if record.sensing_result is not None:
        try:
            new_report, new_notification = GATEWAY.generate_report(
                incident=record.incident,
                sensing=record.sensing_result,
                route_plan=new_route_plan,
                ete=old_decision.ete,
                advisory=None,  # 重規劃時不重新呼叫 RAG，用原有的 SOP 命中
                bundle=bundle,
            )
            logger.info(f"[路線監測] {event_id} 報告書與簡訊已重新生成")
        except Exception as e:
            logger.warning(f"[路線監測] {event_id} 報告書重新生成失敗: {e}，保留原報告")
            if "C1_FAILED" not in degraded:
                degraded.append("C1_REPLAN_FAILED")
    else:
        logger.warning(f"[路線監測] {event_id} 缺少 sensing_result，無法重新生成報告書")
    
    new_decision = DecisionResult(
        trace_id=old_decision.trace_id,
        triggered_by=old_decision.triggered_by,
        level=old_decision.level,
        incident=old_decision.incident,
        routes=new_route_plan,
        ete=old_decision.ete,
        control_center_report=new_report,
        notifications=new_notification,
        degraded=degraded,
        duration_ms=old_decision.duration_ms,
        is_simulated=old_decision.is_simulated,
    )
    record.decision_result = new_decision
    record.route_replan_count += 1

    return RouteMonitorResult(
        event_id=event_id,
        replanned=True,
        old_primary=old_routes.primary.segment_id if old_routes.primary else None,
        new_primary=new_route_plan.primary.segment_id if new_route_plan.primary else None,
        old_secondary=old_routes.secondary.segment_id if old_routes.secondary else None,
        new_secondary=new_route_plan.secondary.segment_id if new_route_plan.secondary else None,
        invalid_reasons=validity.invalid_reasons,
        new_decision_result=new_decision,
    )


def monitor_all_active_routes(as_of: datetime) -> list[RouteMonitorResult]:
    """檢查所有活躍事件的路線有效性，回傳需要更新的清單。

    供 main.py 背景監測迴圈呼叫。
    """
    results: list[RouteMonitorResult] = []
    for event_id in list(_STATE.active_incidents.keys()):
        result = check_and_replan_routes(event_id, as_of)
        if result is not None and result.replanned:
            results.append(result)
    return results
