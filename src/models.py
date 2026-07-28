"""全專案 Pydantic 型別與 Envelope 建構的唯一定義處（01-module-boundaries.md）。

其他模組只能 import 這裡的型別，不得自行定義同名型別或新增/更改欄位。
欄位形狀依 `.kiro/steering/02-data-contract.md`、`.kiro/steering/04-system-architecture.md`
第6節、以及各模組 spec 的驗收測試逐一對照而來；少數規格只用文字描述、沒給精確 schema 的
欄位（標註 [INFERRED]）在實作時如與 Kiro 生成的其他模組對不上，以本檔為準並回頭修正。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 列舉型別
# ---------------------------------------------------------------------------


class DataProvenance(str, Enum):
    """標示一筆資料的來源可信度，決定前端要不要顯示 Demo/Simulated 標記（02-data-contract.md §8）。"""

    PROVIDED = "provided"
    DEMO = "demo"
    DERIVED = "derived"
    GENERATED = "generated"


class ErrorCode(str, Enum):
    """契約定義的八種錯誤碼（02-data-contract.md §7）。不得新增碼值。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    DATA_NOT_FOUND = "DATA_NOT_FOUND"
    RULE_EVALUATION_FAILED = "RULE_EVALUATION_FAILED"
    NO_FEASIBLE_ROUTE = "NO_FEASIBLE_ROUTE"
    KNOWLEDGE_RETRIEVAL_FAILED = "KNOWLEDGE_RETRIEVAL_FAILED"
    MODEL_INVOCATION_FAILED = "MODEL_INVOCATION_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ModuleName(str, Enum):
    """Envelope 的 source_module / target_module 合法值。"""

    API_ORCHESTRATOR = "api_orchestrator"
    DASHBOARD = "dashboard"
    DATA_INGESTION = "data_ingestion"
    SENSING_RULES = "sensing_rules"
    INCIDENT_ROUTING = "incident_routing"
    BEDROCK_ADVISOR = "bedrock_advisor"
    DECISION_REPORTING = "decision_reporting"


class MessageType(str, Enum):
    """全部 message_type 合法值（04-system-architecture.md §5 總表，本次審查最終收斂版）。"""

    DASHBOARD_UPDATED_V1 = "dashboard.updated.v1"
    DECISION_ALERT_V1 = "decision.alert.v1"
    DECISION_CYCLE_START_V1 = "decision.cycle_start.v1"
    DECISION_TASK_UPDATE_V1 = "decision.task_update.v1"
    DECISION_COMPLETED_V1 = "decision.completed.v1"
    RULES_EVALUATED_V1 = "rules.evaluated.v1"
    WHATIF_EVALUATED_V1 = "whatif.evaluated.v1"
    TRACE_ANSWERED_V1 = "trace.answered.v1"
    CHAT_MESSAGE_V1 = "chat.message.v1"
    CHAT_CLEAR_SESSION_V1 = "chat.clear_session.v1"
    CHAT_LOADING_START_V1 = "chat.loading_start.v1"
    CHAT_LOADING_STEP_V1 = "chat.loading_step.v1"
    CHAT_RESPONSE_V1 = "chat.response.v1"
    CHAT_INPUT_LOCK_V1 = "chat.input_lock.v1"
    CHAT_SYSTEM_STATUS_V1 = "chat.system_status.v1"
    CHAT_SESSION_CLEARED_V1 = "chat.session_cleared.v1"


class IncidentSeverity(str, Enum):
    """事件本身的嚴重度分類；不得與 traffic_level（A/B）混用或互相推導（m1-data-ingestion/requirements.md）。"""

    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


TrafficLevel = Literal["A", "B", "normal"]
ReasonCode = Literal[
    "CLOSED",
    "CAPACITY_INSUFFICIENT",
    "NOT_IN_ALTERNATIVES",
    "NOT_DIRECTLY_INTERSECTING",
    "DOWNSTREAM_ONLY",
    "FLOW_DIRECTION_MISMATCH",
    "SATURATED",
    "UNKNOWN_SEGMENT",
    "MISSING_TRAFFIC_SNAPSHOT",
]
"""九值，唯一來源 m4-explanation-chain-and-orchestrator/SPEC-00 §3.3。"""

FindingCode = Literal[
    "SATURATED_BUT_RETAINED",
    "CAPACITY_OVERLOAD",
    "PREDICTED_COLLAPSE",
    "CASCADE_RISK",
    "SCENARIO_COMPARED",
]
"""五值，唯一來源 SPEC-00 §3.4；本次核心範圍只會用到 SATURATED_BUT_RETAINED，其餘為 X1/X2 延伸功能保留值。"""


# ---------------------------------------------------------------------------
# 基礎資料型別（對應 data/ 五個 canonical 檔案，正規化後）
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    field: str | None = None


class TrafficSample(BaseModel):
    """city_traffic_flow.json 正規化後一筆紀錄。"""

    timestamp: datetime
    segment_id: str
    road_name: str
    avg_speed: float | None
    """None 代表缺資料，不等於 0（02-data-contract.md §5）。"""
    vehicle_count: int
    saturation_score: float
    lane_status: str
    provenance: DataProvenance = DataProvenance.PROVIDED


class CrowdSample(BaseModel):
    """signaling_crowd_density.csv 正規化後一筆紀錄（欄位對照 02-data-contract.md §2：BS_ID→station_id、Location_Name→station_name）。"""

    timestamp: datetime
    station_id: str
    station_name: str
    user_count: int
    stay_time_avg: float
    growth_rate: float
    """已是小數率，禁止再除以 100。"""
    roaming_user_pct: float
    """真實資料是帶 % 字串（如 "40%"），loader 必須先移除 % 再除以 100，得到 0.0~1.0。"""
    provenance: DataProvenance = DataProvenance.PROVIDED


class DisplayPoint(BaseModel):
    """display_geometry.json：只控制 SVG 位置，不參與任何決策（02-data-contract.md §8）。"""

    segment_id: str
    x: float
    y: float


class RoadSegment(BaseModel):
    """road_network_topology.json 正規化後一筆路段。"""

    segment_id: str
    name: str
    flow_direction: str
    intersections: list[str]
    """依上游→下游排序（02-data-contract.md §3），存的是路段中文名，需另建 name_to_segment_id 對照。"""
    capacity_vph: int
    alternatives: list[str]
    """單向關係，禁止自動建反向邊。"""
    nearby_stations: list[str] = Field(default_factory=list)
    """空陣列是合法值，不是缺資料，不得自行補值。"""


class Incident(BaseModel):
    """live_incidents.json 一筆事件（欄位對齊真實檔案結構）。"""

    event_id: str
    type: str
    location: str
    affected_segment: str
    affected_road: str | None = None
    """有值時優先於由 affected_segment 推導的結果（02-data-contract.md §3）。"""
    status: str
    severity: IncidentSeverity
    description: str
    timestamp: datetime


class SopClause(BaseModel):
    """emergency_traffic_sop.json 一個 section。"""

    section_number: int
    title: str
    content: str

    @property
    def clause_id(self) -> str:
        return f"SOP-{self.section_number}"


class NormalizedDataBundle(BaseModel):
    """M1 loaders.py 的輸出，其餘模組只能透過這個物件取用資料，不得直接讀 data/（01-module-boundaries.md 規則2）。"""

    traffic: list[TrafficSample]
    crowd: list[CrowdSample]
    road_network: list[RoadSegment]
    incidents: list[Incident]
    sop: list[SopClause]
    loaded_at: datetime


# ---------------------------------------------------------------------------
# 感知與規則（M1 P1-P5）
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """[INFERRED] 規則命中時引用的原始資料片段，供決策依據面板（F7）與 Trace 顯示；
    規格文件只以文字描述「引用門檻數值 vs 假設值的比較」，未給精確 schema，實作時如與其他模組對不上以此為準。
    """

    field: str
    value: float | str
    threshold: float | str | None = None


class RuleHit(BaseModel):
    """P4 規則引擎命中一條 SOP 條款。"""

    clause_id: str
    """格式 "SOP-N"。"""
    segment_id: str | None = None
    station_id: str | None = None
    evidence: EvidenceRef
    is_primary: bool = False
    """True 表示這是事件的主因 SOP，其餘為並行命中（不得被改寫）。"""


class SensingResult(BaseModel):
    """M1 rules.py 的輸出。"""

    traffic_level: TrafficLevel
    rule_hits: list[RuleHit]
    as_of: datetime
    multilingual_required: bool = False
    """SOP-6 是否命中，決定 C4 要不要產生多語版本。"""


# ---------------------------------------------------------------------------
# 路網規劃（M2 R1-R5）
# ---------------------------------------------------------------------------


class RouteRequest(BaseModel):
    incident: Incident
    bundle: NormalizedDataBundle
    as_of: datetime


class RouteCandidate(BaseModel):
    """一個候選路段的完整評估結果，供決策依據面板顯示（04-system-architecture.md §6 routes.candidates）。"""

    segment_id: str
    name: str
    eligible: bool
    reason_code: ReasonCode | None = None
    """不合格時的排除理由；合格時為 None。"""
    saturation_score: float | None
    capacity_vph: int
    snapshot_at: datetime | None
    """as-of 車流快照時間，找不到時為 None（記 MISSING_TRAFFIC_SNAPSHOT，不當作 0）。"""


class RouteFinding(BaseModel):
    finding_code: FindingCode
    segment_ids: list[str]
    evidence: dict
    detail: str | None = None
    """禁止 LLM 生成（m4-explanation-chain-and-orchestrator/SPEC-M4A §3）。"""


class RoutePlan(BaseModel):
    """M2 routing.py 的輸出。"""

    primary: RouteCandidate | None
    secondary: RouteCandidate | None
    excluded: list[RouteCandidate]
    findings: list[RouteFinding]
    candidates: list[RouteCandidate]
    """完整候選評估清單（含合格與不合格），DecisionResult.routes.candidates 直接取用。"""
    no_feasible_route: bool = False
    duration_ms: int = 0
    within_60_second_sla: bool = True


# ---------------------------------------------------------------------------
# ETE 與報告（M4）
# ---------------------------------------------------------------------------


class EteEstimate(BaseModel):
    """M4 reporting.py 的 A3 輸出（m4-decision-reporting/requirements.md §2）。"""

    minutes: int
    recovery_at: str
    """格式 "YYYY-MM-DD HH:MM"（SOP §6 規定，非 ISO 8601）。"""
    formula: str
    """固定文字，附代入數值，供解釋鏈引用，例："60 + max(0,(1.0-0.5)*60) = 90"。"""
    base_clearance: int
    average_saturation: float


class Notification(BaseModel):
    """C4 多語簡訊，單一物件（不是清單）——SOP-6 未觸發時只有 zh 有值。"""

    zh: str
    en: str | None = None
    ja: str | None = None
    ko: str | None = None


# ---------------------------------------------------------------------------
# Agent / RAG / What-if（M3）
# ---------------------------------------------------------------------------


class SopEvidence(BaseModel):
    """LLM 回答附帶的 SOP 依據；任何 LLM 回答至少一筆（01-module-boundaries.md §3）。"""

    section_number: int
    title: str
    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class BedrockAdvisory(BaseModel):
    """M3 run_agent() 的輸出；事實欄位由呼叫端（orchestrator）覆寫，此處欄位僅供參考不得直接採信為最終值。"""

    text: str
    fact_source: Literal["python_decision_facts"] = "python_decision_facts"
    sop_evidence: list[SopEvidence]


class ScenarioOverrides(BaseModel):
    """What-if 假設參數，key 格式 "{entity}.{field}"，例如 {"BS_MRT_BL17.User_Count": 40000}。"""

    overrides: dict[str, float | int | str]


class WhatIfRequest(BaseModel):
    """POST /api/what-if 請求本體。"""

    session_id: str
    content: str
    """使用者原始問句；是否為前瞻假設由 orchestrator 依 SPEC-O3 §4 規則判斷，這裡不判斷。"""
    current_trace_id: str | None = None
    scenario_overrides: dict[str, float | int | str] | None = None
    base_decision_id: str | None = None
    base_as_of: datetime | None = None
    correlation_id: str


class WhatIfResult(BaseModel):
    """前瞻假設分支的回應 payload（message_type=whatif.evaluated.v1）。"""

    simulation_only: Literal[True] = True
    rule_hits: list[RuleHit]
    route_plan: RoutePlan | None
    ete: EteEstimate | None
    sop_evidence: list[SopEvidence]
    differences_from_base: list[dict]
    """[INFERRED] 差異項目的精確 schema 規格未給，實作時先用 {field, base_value, new_value} 起步。"""
    summary: str
    suggested_questions: list[str] = Field(default_factory=list)


class TraceAnswer(BaseModel):
    """回溯追問／無進行中週期分支的回應 payload（message_type=trace.answered.v1）。"""

    trace_id: str | None
    answer_text: str


# ---------------------------------------------------------------------------
# 決策結果與 Dashboard（M5 組裝）
# ---------------------------------------------------------------------------


class DecisionResult(BaseModel):
    """M5 orchestrator.py 組裝的統一輸出（04-system-architecture.md §6，最終版）。"""

    trace_id: str
    triggered_by: list[str]
    level: TrafficLevel | None
    incident: Incident | None
    routes: RoutePlan | None
    ete: EteEstimate | None
    control_center_report: str | None
    """C1+C2+C3 全文合一；生成失敗時 null，degraded 記 "C1_FAILED"。"""
    notifications: Notification | None
    degraded: list[str] = Field(default_factory=list)
    duration_ms: int
    is_simulated: bool
    """依本次決策實際引用的資料來源計算，不得寫死 True（引用真實 provided 資料時應為 False）。"""


class KpiSummary(BaseModel):
    """F1 五張 KPI 卡片的內容。[2026-07-28總架構師補充：業界通用版原型，供團隊雕琢]

    這五張卡片原本沒有任何 spec 定義過要顯示什麼，選擇依據是「交通指揮中心值班人員
    一眼要看到的五件事」（類比一般 SRE/維運 Dashboard 的黃金指標：現況、告警數、
    健康度、覆蓋率、系統模式）：
        1. active_incident_count — 進行中事件數，最直接的工作量指標
        2. current_level         — 全路網目前最高應變等級（多筆進行中事件時取最高者）
        3. average_saturation    — 全路網平均飽和度，反映整體壅塞程度的單一數字
        4. multilingual_alert_count — SOP-6 觸發站點數，多語通報是否啟動的量化指標
        5. system_mode           — "live"（Bedrock可用）｜"degraded"（保底模式），
                                    讓值班人員知道現在看到的建議書是AI生成還是模板

    crowd_data_classification 沿用 02-data-contract.md §8 的既有規則
    （demo→顯示Demo標記；unavailable→顯示「資料未提供」）。
    """

    crowd_data_classification: DataProvenance | Literal["unavailable"]
    active_incident_count: int = 0
    current_level: TrafficLevel | None = None
    average_saturation: float | None = None
    multilingual_alert_count: int = 0
    system_mode: Literal["live", "degraded"] = "live"


class DashboardPayload(BaseModel):
    """GET /api/dashboard 的回應 payload。"""

    kpis: KpiSummary
    active_incidents: list[Incident] = Field(default_factory=list)
    as_of: datetime


# ---------------------------------------------------------------------------
# Message Envelope（02-data-contract.md §7 唯一建構入口）
# ---------------------------------------------------------------------------

EnvelopePayload = (
    DashboardPayload
    | DecisionResult
    | WhatIfResult
    | TraceAnswer
    | SensingResult
    | dict
)
EnvelopeStatus = Literal["ok", "partial", "error"]


class MessageEnvelope(BaseModel):
    schema_version: str
    message_id: str
    correlation_id: str
    message_type: MessageType
    source_module: ModuleName
    target_module: ModuleName
    generated_at: datetime
    status: EnvelopeStatus = "ok"
    provenance: list[DataProvenance] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
    payload: EnvelopePayload


def build_envelope(
    message_type: MessageType,
    payload: EnvelopePayload,
    *,
    correlation_id: str,
    status: EnvelopeStatus = "ok",
    source_module: ModuleName = ModuleName.API_ORCHESTRATOR,
    target_module: ModuleName = ModuleName.DASHBOARD,
    provenance: list[DataProvenance] | None = None,
    warnings: list[str] | None = None,
    errors: list[ErrorDetail] | None = None,
) -> MessageEnvelope:
    """Envelope 建構的唯一入口（m5-api-orchestrator-dashboard/design.md）。

    schema_version / message_id / generated_at 在這裡產生，呼叫端不得自行指定，
    確保同一流程的多筆推播格式一致、message_id 不重複。
    """
    raise NotImplementedError(
        "TODO(Kiro): 依 m5-api-orchestrator-dashboard/design.md「Data Models」節實作："
        "schema_version 用固定字串常數；message_id 用 uuid4；generated_at 用 "
        "datetime.now(tz=Asia/Taipei) 並輸出 ISO 8601 +08:00。"
    )
