"""全專案 Pydantic 型別與 Envelope 建構的唯一定義處（01-module-boundaries.md）。

其他模組只能 import 這裡的型別，不得自行定義同名型別或新增/更改欄位。
欄位形狀依 `.kiro/steering/02-data-contract.md`、`.kiro/steering/04-system-architecture.md`
第6節、以及各模組 spec 的驗收測試逐一對照而來；少數規格只用文字描述、沒給精確 schema 的
欄位（標註 [INFERRED]）在實作時如與 Kiro 生成的其他模組對不上，以本檔為準並回頭修正。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
"""Envelope 的 schema_version 固定值，唯一來源 `contracts/module_exchange_contract.json` 第 3 行。"""

TZ_TAIPEI = timezone(timedelta(hours=8))
"""00-tech-stack.md §7：時間一律 ISO 8601 + Asia/Taipei（+08:00），禁止無時區字串。"""

DEFAULT_BEDROCK_MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
"""`BEDROCK_MODEL_ID` 未設定時的預設模型（W1／A2／C1-C4／M4B 共用）。

[2026-08-01] 原本三處各自寫死 `anthropic.claude-3-5-sonnet-20241022-v2:0`，
該版本在 us-west-2 已 end-of-life，實測回
`ResourceNotFoundException: This model version has reached the end of its life`。
改用 inference profile 形式的 Sonnet 4.5（AgentCore CLI 骨架的預設值亦為此），
並收斂成單一常數，避免下次模型下架時又要三個檔案各改一次。

環境變數 `BEDROCK_MODEL_ID` 仍優先於本值（00-tech-stack.md §5）。
"""

DEFAULT_REPORT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
"""C1-C4（交控建議書／多語簡訊）專用的預設模型。

[2026-08-01 實測後分流] 決策週期 40 秒裡有 29.4 秒是這兩個生成：
C1-C3 建議書 20.8s（1508 字）、C4 四語簡訊 8.6s。而決定性模組（讀資料、
規則、路網、ETE）加起來是 **3 毫秒**——使用者感受到的「卡」百分之百來自 LLM。

C1-C4 的任務性質是**唯讀轉換**：所有數字、路段、條款編號都已經由 Python 算好
寫進 facts block，LLM 只負責把既有事實寫成人話（SPEC-00 鐵律①）。這種任務用
Haiku 就夠，換來約一倍的速度。

需要理解與規劃的兩個地方**維持 Sonnet**，不套用本值：
  - A2 規劃器（要從自然語言事件推工具序列）
  - W1 What-if 對話（要理解使用者的自然語言假設並選對工具與欄位）

環境變數 `BEDROCK_REPORT_MODEL_ID` 優先；若只設了 `BEDROCK_MODEL_ID` 而沒設
這一個，仍以本值為準——想讓建議書也跑 Sonnet 請顯式設定 `BEDROCK_REPORT_MODEL_ID`。
"""


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


class ToolName(str, Enum):
    """A2 規劃器可選的工具白名單，唯一來源 SPEC-00 §3.2（十二值，不得新增）。

    SPEC-O2 §3.2 護欄①：A2 LLM 產出的 ToolPlan 若出現本列舉以外的工具名，
    整份計畫作廢並降級為靜態分派鏈。
    """

    RAG_SEARCH = "RAG_SEARCH"                    # K3 SOP 檢索
    GRAPH_BUILD = "GRAPH_BUILD"                  # R1
    UPSTREAM_JUDGE = "UPSTREAM_JUDGE"            # R2
    CANDIDATE_FILTER = "CANDIDATE_FILTER"        # R3
    ROUTE_SELECT = "ROUTE_SELECT"                # R4
    CALC_ETE = "CALC_ETE"                        # A3
    COUNT_INTERSECTIONS = "COUNT_INTERSECTIONS"  # SOP-5 警力估算；歸屬 routing.py
    CAPACITY_CHECK = "CAPACITY_CHECK"            # X2（延伸）
    FORECAST_MODEL = "FORECAST_MODEL"            # X1/X2（延伸）
    CASCADE_ANALYSIS = "CASCADE_ANALYSIS"        # X2（延伸）
    FORMAT_REPORT = "FORMAT_REPORT"              # C1
    TRANSLATE = "TRANSLATE"                      # C4


R_CHAIN_TOOLS: frozenset[ToolName] = frozenset(
    {
        ToolName.GRAPH_BUILD,
        ToolName.UPSTREAM_JUDGE,
        ToolName.CANDIDATE_FILTER,
        ToolName.ROUTE_SELECT,
    }
)
"""R1-R4 路網工具鏈。SPEC-O2 §3.2 護欄②「§2 類事件必含 R 鏈與 CALC_ETE」的判定集合。

R5（排除理由記錄）不在 ToolName 列舉內——SPEC-00 §3.2 只列到 ROUTE_SELECT，
R5 的產出是 RoutePlan.excluded 欄位，隨 ROUTE_SELECT 一併回傳，不是獨立可規劃的工具。
"""


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
    city_response: bool = False
    """[2026-07-28總架構師補充：回應Kiro Phase 1.2審查] 只在 clause_id="SOP-1" 且
    segment_id 屬於城市應變觸發限定路段（RD_TPE_001/002，SOP原文）時為 True。

    由 `rules.py` 算一次寫進這裡，下游（`reporting.py` 的 C2 號誌建議、
    `orchestrator.py` 的 SPEC-O2 §1-A 靜態分派「同步觸發替代路徑引導」判斷）
    直接讀這個欄位，不得各自重新定義一份城市應變路段清單——重複定義同一個規則
    在不同檔案裡，正是這次整個審查過程反覆抓到的同一種 bug（`ReasonCode` 曾經
    三處定義互相對不上），這裡刻意用欄位而不是常數重複，杜絕同樣的問題再發生。
    """


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
# A2 編排規劃（SPEC-O2 §3 折衷制的 LLM 規劃器輸出）
# ---------------------------------------------------------------------------


class ToolPlanStep(BaseModel):
    """ToolPlan 的單一步驟。

    `args_hint` 是 LLM 給的參數「提示」而非權威值——SPEC-00 鐵律①「LLM 只表達、
    不改寫」：實際傳給決定性模組的參數一律由 orchestrator 從 IncidentEvent／
    NormalizedDataBundle 取得，不採信 LLM 生成的 event_id／路段代碼／數值。
    args_hint 只用於留痕（讓 F7 面板顯示「A2 當時想怎麼呼叫」）與除錯。
    """

    tool: ToolName
    args_hint: dict = Field(default_factory=dict)


class ToolPlan(BaseModel):
    """A2 LLM 規劃器的輸出契約（SPEC-O2 §3.1）。

    規劃器「不執行工具、不產生數值結果」，只回傳工具序列；執行由 orchestrator
    的 EXECUTE 階段依 GATEWAY 呼叫決定性模組完成。
    """

    steps: list[ToolPlanStep] = Field(default_factory=list)

    def tool_names(self) -> list[ToolName]:
        """依序回傳工具名，供護欄②的必要步驟檢查與 record_step 留痕使用。"""
        return [s.tool for s in self.steps]


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
    projected_risks: dict | None = None
    """二階效應推演（`risk_projection.projection_to_dict()` 的輸出）。

    [2026-08-01 新增] 建議書原本只回答「現在該做什麼」，沒有回答「這麼做之後
    會怎樣」。實測 ACC_001：系統建議改道市民大道四段（當下飽和度 0.78），
    而該路段在 20 分鐘內就會達 A 級——指揮官照著做，然後在 22:30 面對一個
    本來可以預先處置的新事件。

    這個欄位裝的是「接下來 60 分鐘會出什麼問題、什麼時候、依 SOP 該怎麼辦」，
    全部由 `src/risk_projection.py` 確定性算出，LLM 只負責寫成通順的段落。
    """
    
    # [2026-08-01新增] 同路段多事件合併資訊
    merged_incident_info: dict | None = None
    """同路段有多個事件時，包含合併事件的詳細資訊：
    {
        "event_ids": [...],
        "count": int,
        "max_ete_minutes": int,
        "merged_ete_minutes": int,
        "descriptions": [...],
    }
    """


class KpiSummary(BaseModel):
    """F1 五張 KPI 卡片的內容。[2026-07-28總架構師補充：業界通用版原型，供團隊雕琢]

    這五張卡片原本沒有任何 spec 定義過要顯示什麼，選擇依據是「交通指揮中心值班人員
    一眼要看到的五件事」（類比一般 SRE/維運 Dashboard 的黃金指標：現況、告警數、
    健康度、覆蓋率、系統模式）：
        1. active_incident_count — 進行中事件數，最直接的工作量指標
        2. current_level         — 全路網目前最高應變等級（多筆進行中事件時取最高者）
        3. average_saturation    — 全路網平均飽和度，反映整體壅塞程度的單一數字
        4. multilingual_alert_count — SOP-6 觸發站點數，多語通報是否啟動的量化指標
        5. system_mode           — "live"（Bedrock 實際可用）｜"degraded"（保底模式或
                                    Bedrock 不通）｜"unknown"（尚未驗證），
                                    讓值班人員知道現在看到的建議書是AI生成還是模板

    crowd_data_classification 沿用 02-data-contract.md §8 的既有規則
    （demo→顯示Demo標記；unavailable→顯示「資料未提供」）。
    """

    crowd_data_classification: DataProvenance | Literal["unavailable"]
    active_incident_count: int = 0
    current_level: TrafficLevel | None = None
    average_saturation: float | None = None
    multilingual_alert_count: int = 0
    system_mode: Literal["live", "degraded", "unknown"] = "unknown"
    """[2026-08-01] 新增 "unknown"，預設值從 "live" 改成 "unknown"。

    原本只有 live/degraded 二分，而值是從 `USE_BEDROCK` 旗標推導的——旗標說的是
    「允不允許呼叫」，不是「呼叫通不通」。憑證失效時這張卡片會顯示 **Live**，
    但建議書早就退成模板版了。

    現在改讀 `src/bedrock_status` 的實際探測結果。加第三態是因為「還沒驗證完」
    歸進哪一邊都是說謊：歸 live 就是原本那個 bug，歸 degraded 又會讓剛啟動的
    系統看起來壞掉。預設值同理從 "live"（樂觀假設）改成 "unknown"（誠實）。
    """


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

    `correlation_id` 相反地必須由呼叫端傳入：同一個決策週期（同一 trace_id）發出的
    多筆推播共用一個 correlation_id，前端才能把 cycle_start / task_update /
    completed 串成同一次決策，這是 m5-api-orchestrator-dashboard/requirements.md
    的 correlation_id 一致性要求，不能在這裡自動生成。
    """
    return MessageEnvelope(
        schema_version=SCHEMA_VERSION,
        message_id=str(uuid.uuid4()),
        correlation_id=correlation_id,
        message_type=message_type,
        source_module=source_module,
        target_module=target_module,
        generated_at=datetime.now(tz=TZ_TAIPEI),
        status=status,
        provenance=provenance or [],
        warnings=warnings or [],
        errors=errors or [],
        payload=payload,
    )
