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

import asyncio
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
    ToolName,
)


# ---------------------------------------------------------------------------
# ModuleGateway：M5 對 M1-M4 的邊界（m5-api-orchestrator-dashboard/design.md）
# ---------------------------------------------------------------------------


class ModuleGateway(Protocol):
    def load_data(self) -> NormalizedDataBundle: ...

    def evaluate_rules(
        self,
        bundle: NormalizedDataBundle,
        incident: Incident | None = None,
        as_of: datetime | None = None,
    ) -> SensingResult: ...

    def plan_routes(self, request: RouteRequest) -> RoutePlan: ...

    def calculate_ete(self, incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate: ...

    # SPEC-00 §3.2 ToolName.COUNT_INTERSECTIONS：SOP-5（§5）警力估算 = 路口數 × 2。
    # 歸屬 routing.py（模組2）——需要路網拓樸才算得出受影響路口數。
    def count_intersections(
        self, incident: Incident, bundle: NormalizedDataBundle
    ) -> int: ...

    # [2026-07-28架構複查新增] `bundle` 參數：回應SPEC-O2「§5必含COUNT_INTERSECTIONS」——
    # SOP-5（號誌故障）需要用路網拓樸算受影響路口數（`routing.count_affected_intersections()`），
    # 警力人數=路口數×2，這個計算需要 bundle 才能做，之前完全沒傳進來，是 §5 這條 SOP 的
    # 人力派遣建議一直缺少具體人數的原因。
    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
        bundle: NormalizedDataBundle,
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
        self,
        bundle: NormalizedDataBundle,
        incident: Incident | None = None,
        as_of: datetime | None = None,
    ) -> SensingResult:
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=8))
        if as_of is None:
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

    def count_intersections(self, incident: Incident, bundle: NormalizedDataBundle) -> int:
        return 3

    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
        bundle: NormalizedDataBundle,
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
        self,
        bundle: NormalizedDataBundle,
        incident: Incident | None = None,
        as_of: datetime | None = None,
    ) -> SensingResult:
        from src.rules import evaluate_rules
        return evaluate_rules(bundle, incident, as_of)

    def plan_routes(self, request: RouteRequest) -> RoutePlan:
        from src.routing import plan_route
        return plan_route(request)

    def calculate_ete(self, incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate:
        from src.reporting import calculate_ete
        return calculate_ete(incident, bundle)

    def count_intersections(self, incident: Incident, bundle: NormalizedDataBundle) -> int:
        """SOP-5 警力估算的路口數。受影響路段以 A1 的 affected_source 為準。"""
        from src.routing import count_affected_intersections

        affected = incident.affected_road or incident.affected_segment
        return count_affected_intersections(bundle, affected)

    def generate_report(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
        advisory: BedrockAdvisory | None,
        bundle: NormalizedDataBundle,
    ) -> tuple[str, Notification | None]:
        from src.reporting import generate_report
        return generate_report(incident, sensing, route_plan, ete, advisory, bundle)

    def run_agent(
        self,
        incident: Incident,
        sensing: SensingResult,
        route_plan: RoutePlan | None,
        ete: EteEstimate,
    ) -> BedrockAdvisory:
        """呼叫 W1 Agent 取得 SOP 建議。失敗時降級回 StubGateway 的假回傳。

        `USE_BEDROCK=false` 時直接走 stub，不進 Agent——00-tech-stack.md §6 保底模式
        要求該旗標為 false 時系統不得呼叫 Bedrock。原本只靠 `except` 接住連線失敗，
        等於保底模式下仍會真的發出一次 ConverseStream 請求（離線或憑證過期時每次
        決策都要等它逾時），旗標形同虛設。

        [2026-08-01 修正兩點]
        1. **不再靜默降級**：原本 `except Exception: return self._stub.run_agent(...)`
           連 log 都沒有。實測 W1 在這裡逾時，`DecisionResult.degraded` 仍是 `[]`，
           呼叫端第 819 行的 `logger.warning` 也永遠不會執行（例外在這裡就被吃掉了）。
           這違反本專案反覆引用的「永不沉默」原則。現在改成記錄並往上拋，由呼叫端
           寫進 `degraded`。
        2. **逾時預算縮短**：用 `ADVISORY_TIMEOUT_S`（15s）而非 W1 對話的 60s。
           實測這個呼叫要 31.6 秒（4 輪 tool-call 往返），佔掉決策週期約一半時間，
           而它產出的 `BedrockAdvisory` **下游沒有任何地方使用**（`generate_report()`
           收了這個參數但內部沒讀，`DecisionResult` 也沒有對應欄位）。
           在確認要不要保留這個呼叫之前，先把它的時間成本關進 15 秒的籠子裡。
        """
        if os.getenv("USE_BEDROCK", "true").lower() != "true":
            return self._stub.run_agent(incident, sensing, route_plan, ete)

        try:
            from src.agent.whatif_agent import process_whatif
            from src.llm import ADVISORY_TIMEOUT_S
            from src.session.models import W1Context

            # 組一個簡單的 context 讓 Agent 產出建議
            context = W1Context(
                session_id="__orchestrator__",
                new_message=f"事件 {incident.event_id} 發生在 {incident.location}，請提供 SOP 建議",
                history=[],
                accumulated_assumptions={},
            )
            response = process_whatif(context, timeout_s=ADVISORY_TIMEOUT_S)
            if response.source_mode == "degraded":
                raise RuntimeError("W1 Agent 回傳降級結果（逾時或 LLM 不可用）")
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
        except Exception as e:
            # 往上拋而不是靜默換 stub——理由見 docstring 修正第 1 點。
            logger.warning(f"W1 advisory 取得失敗，決策週期改以無 advisory 繼續: {e}")
            raise


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

    對照表（m5-api-orchestrator-dashboard/design.md）：
        Road_Collapse_Accident → SOP-2 → requires_rerouting=True
        Crowd_Surge_Injury     → SOP-3 → requires_rerouting=False
        Power_Failure          → SOP-5 → requires_rerouting=False
        其他                    → None  → requires_rerouting=False
    """
    type_map = {
        "Road_Collapse_Accident": ("SOP-2", True),
        "Crowd_Surge_Injury": ("SOP-3", False),
        "Power_Failure": ("SOP-5", False),
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
# 靜態分派表（SPEC-O2 §2）
#
# 折衷制的「確定性」那一半：規則觸發流程與 LLM 規劃器降級時都走這張表。
# 表本身零 LLM——規則→動作由 SOP 明文寫死，沒有判斷空間（SPEC-O2 §1）。
# ---------------------------------------------------------------------------


_CLAUSE_CHAIN: dict[str, list[ToolName]] = {
    # §2 車禍/路障：R 鏈四步 + ETE（SPEC-O2 §2「[R1→R2→R3→R4→R5, A3]」）
    "§2": [
        ToolName.GRAPH_BUILD,
        ToolName.UPSTREAM_JUDGE,
        ToolName.CANDIDATE_FILTER,
        ToolName.ROUTE_SELECT,
        ToolName.CALC_ETE,
    ],
    # §1-A / §1-B 壅塞分級：P5 摘要包 → C1，不做路網重規劃
    "§1": [ToolName.CALC_ETE],
    "§1-A": [ToolName.CALC_ETE],
    "§1-B": [ToolName.CALC_ETE],
    # §3 大眾運輸分流：P5 摘要包 → C1, C3
    "§3": [ToolName.CALC_ETE],
    # §4 大型活動散場：自動連動 §3（見 _expand_auto_chained_clauses）
    "§4": [ToolName.CALC_ETE],
    # §5 停電/號誌失效：警力 = 路口數 × 2
    "§5": [ToolName.COUNT_INTERSECTIONS, ToolName.CALC_ETE],
    # §6 只設 multilingual flag，不分派任務（SPEC-O2 §2「§6 → 不分派」）
    "§6": [],
}
"""條款 → 主責工具鏈。唯一來源 SPEC-O2 §2 靜態分派表。

RAG_SEARCH 與 FORMAT_REPORT 不寫在表內：前者是每條鏈固定的前置（查 SOP 依據），
後者是固定收尾（C1 建議書），由 `static_dispatch_chain()` 統一補上，避免每列重複。
"""


_SOP_TO_CLAUSE: dict[str, str] = {
    "SOP-1": "§1",
    "SOP-2": "§2",
    "SOP-3": "§3",
    "SOP-4": "§4",
    "SOP-5": "§5",
    "SOP-6": "§6",
}
"""A1 分類產出的 SOP-n 與 SPEC-O2 條款編號的對應。"""


def expand_auto_chained_clauses(clauses: list[str]) -> list[str]:
    """§4 自動連動 §3（SPEC-O2 §2.1，確定性，不交 LLM）。

    批次含 §4 時追加 §3；`auto_chained` 註記由呼叫端寫進 DISPATCH 紀錄。
    回傳保持原順序、去重。
    """
    expanded = list(clauses)
    if "§4" in expanded and "§3" not in expanded:
        expanded.append("§3")
    seen: set[str] = set()
    return [c for c in expanded if not (c in seen or seen.add(c))]


def static_dispatch_chain(
    clauses: list[str],
    *,
    multilingual: bool = False,
) -> list[ToolName]:
    """把命中條款映射成工具序列（SPEC-O2 §2 + §2.2 同主責合併）。

    同批次多條規則映射到同一模組鏈時只保留一份（§2.2「同主責合併」），
    這裡以「保序去重」實作：先照條款順序展開，再去掉重複工具。

    Args:
        clauses: 條款編號清單（如 ["§1-A", "§4"]）；已由呼叫端做過 §4→§3 展開
        multilingual: GlobalState.multilingual；true 時追加 TRANSLATE（C4）
    """
    sequence: list[ToolName] = [ToolName.RAG_SEARCH]

    for clause in clauses:
        sequence.extend(_CLAUSE_CHAIN.get(clause, []))

    sequence.append(ToolName.FORMAT_REPORT)
    if multilingual:
        sequence.append(ToolName.TRANSLATE)

    seen: set[ToolName] = set()
    return [t for t in sequence if not (t in seen or seen.add(t))]


def static_chain_for_classification(
    classification: dict,
    *,
    multilingual: bool = False,
) -> list[ToolName]:
    """事件注入流程的降級目標：把 A1 分類結果轉成靜態鏈（SPEC-O2 §3.2）。"""
    primary_sop = classification.get("primary_sop")
    clause = _SOP_TO_CLAUSE.get(primary_sop or "", "§1")
    return static_dispatch_chain(
        expand_auto_chained_clauses([clause]),
        multilingual=multilingual,
    )


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


_STATE = GlobalState()


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

    # SPEC-O3 §2 的 TriggeredRule 欄位名是 `rule`（值本身已含 § 前綴，如 "§1-A"）。
    # 原本只讀 `section` 並自行補 §，跟契約對不起來——規則引擎照 SPEC-O3 傳 `rule`
    # 時會整批取不到值、triggered_by 一律退化成 ["§1"]。這裡以 `rule` 為主，
    # 保留 `section` 作為舊呼叫端的相容路徑。
    triggered_by: list[str] = []
    for b in batch:
        rule = b.get("rule")
        if rule:
            triggered_by.append(str(rule))
            continue
        section = b.get("section")
        if section:
            triggered_by.append(f"§{section}")
    if not triggered_by:
        triggered_by = ["§1"]

    try:
        open_trace(trace_id, triggered_by)
    except ValueError:
        pass  # trace 已存在（重入保護）

    # PLAN：靜態分派表（SPEC-O2 §2，零 LLM）。
    # §4 自動連動 §3（§2.1）在這裡展開，並於紀錄中註明 auto_chained 供追溯。
    expanded = expand_auto_chained_clauses(triggered_by)
    planned_tools = static_dispatch_chain(expanded, multilingual=_STATE.multilingual)
    plan_input: dict = {"batch": batch, "clauses": expanded}
    if expanded != triggered_by:
        plan_input["auto_chained"] = "§3"
        plan_input["reason"] = "SOP §4 明文連動"
    try:
        record_step(
            trace_id,
            "A2",
            "PLAN",
            plan_input,
            {"planned_by": "static_dispatch", "tools": [t.value for t in planned_tools]},
        )
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


_TASK_LABELS: dict[str, str] = {
    "routing_started": "規劃替代路線",
    "routing_done": "替代路線完成",
    "ete_started": "計算恢復時間",
    "ete_done": "恢復時間完成",
    "report_started": "生成交控建議書",
    "report_done": "交控建議書完成",
    "explain_started": "生成決策說明",
    "explain_done": "決策說明完成",
}
"""`decision.task_update.v1` 的人話標籤。

前端原本只把 `status` 這種機器碼直接印進活動面板（`routing_started`），
指揮官看不懂。標籤放後端而不是前端，是因為狀態碼的新增總是跟後端流程一起
發生——放前端就會出現「後端加了新步驟、畫面顯示原始英文代碼」的漂移。
"""

_TASK_ETA_SECONDS: dict[str, int] = {
    "report_started": 20,
    "explain_started": 10,
}
"""各階段的預估耗時（秒），供前端畫進度條。

數字來自實測（見 `llm.py` 的 `CONVERSE_TIMEOUT_S` 註解：建議書生成約 20 秒）。
只有真的會讓使用者等的 LLM 階段需要，確定性運算是毫秒級不必畫。
**這是給進度條看的估計值，不是逾時預算**——真正的逾時在 `llm.py`。
"""


def _record_route_plan_step(trace_id: str, event: Incident, route_plan: RoutePlan | None) -> None:
    """把路網規劃結果寫進決策軌跡。

    [2026-08-01 補漏：回溯追問對路線問題永遠答不出來]
    ----------------------------------------------
    `handle_incident()` 原本只記四種 step：A2 的 SET_FLAG／PLAN／CYCLE_SUMMARY，
    以及 SOP-5 的 COUNT_INTERSECTIONS。**路網規劃的結果從來沒有進過 trace**——
    `RoutePlan` 只存在於回傳的 `DecisionResult` 裡。

    後果是 `decision_trace.answer_trace_query()` 的 Step 2（依 segment_id 篩選
    相關紀錄）幾乎永遠篩不到東西：整條 trace 裡唯一帶路段的是 CYCLE_SUMMARY 的
    `subject_segment_ids=[事故路段]`。所以：

        問「延吉街為什麼不能走」→「此路段未列入本次判斷」

    但延吉街明明就在 `route_plan.excluded` 裡、理由是容量不足——資料算出來了，
    只是沒有留痕，於是解釋鏈拿不到。這正是回溯追問最該回答的那種問題。

    ActorCode 用 R4（路線選擇），與 SPEC-O1 §5「agent 欄位標示執行者」一致。
    `excluded`／`findings` 用 `record_step` 既有的參數帶進去，那兩個參數本來就是
    為這件事設計的，只是一直沒有呼叫端使用。
    """
    if route_plan is None:
        return

    from src.decision_trace import ExcludedItem, Finding, record_step

    subject_ids: list[str] = []
    if route_plan.primary:
        subject_ids.append(route_plan.primary.segment_id)
    if route_plan.secondary:
        subject_ids.append(route_plan.secondary.segment_id)

    excluded = [
        ExcludedItem(
            segment_id=exc.segment_id,
            reason_code=exc.reason_code,
            reason_detail=(
                f"{exc.name}：飽和度 {exc.saturation_score}、容量 {exc.capacity_vph} vph"
            ),
        )
        for exc in route_plan.excluded
        if exc.reason_code  # reason_code 為 None 的候選不是「被排除」，不該記進來
    ]

    findings = [
        Finding(
            finding_code=f.finding_code,
            segment_ids=list(f.segment_ids),
            evidence=dict(f.evidence or {}),
        )
        for f in (route_plan.findings or [])
    ]

    try:
        record_step(
            trace_id,
            "R4",
            "TOOL_CALL",
            {"event_id": event.event_id, "affected_segment": event.affected_segment},
            {
                "primary": route_plan.primary.segment_id if route_plan.primary else None,
                "secondary": route_plan.secondary.segment_id if route_plan.secondary else None,
                "excluded_count": len(excluded),
                "no_feasible_route": route_plan.no_feasible_route,
            },
            tool=ToolName.ROUTE_SELECT.value,
            sop_ref="§2",
            excluded=excluded,
            findings=findings,
            subject_segment_ids=subject_ids,
            duration_ms=route_plan.duration_ms,
        )
    except Exception as e:  # noqa: BLE001 - 留痕失敗不該讓決策週期中斷
        logger.warning(f"record_step ROUTE_SELECT 失敗: {e}")


async def _broadcast_task_update(
    ws_broadcaster,
    trace_id: str,
    dispatch_seq: int,
    status: str,
) -> None:
    """直接 await 推播 decision.task_update.v1，確保即時送出。

    [2026-08-01] 補上 `label` 與 `eta_seconds`：前端要靠這兩個欄位在事件注入後
    顯示「生成交控建議書中…」的進度條，而不是畫面靜止 20 秒讓人以為當掉了。
    """
    if ws_broadcaster is None:
        return
    try:
        payload = {
            "trace_id": trace_id,
            "dispatch_seq": dispatch_seq,
            "status": status,
            "label": _TASK_LABELS.get(status, status),
        }
        eta = _TASK_ETA_SECONDS.get(status)
        if eta is not None:
            payload["eta_seconds"] = eta
        await ws_broadcaster({
            "message_type": "decision.task_update.v1",
            "payload": payload,
        })
    except Exception:
        pass  # 推播失敗不影響主流程


async def handle_incident(event: Incident, ws_broadcaster=None) -> DecisionResult:
    """D4 監聽器呼叫入口，對應 REST POST /api/incidents/evaluate。

    七階段生命週期：OPEN→FLAGS→PLAN→EXECUTE→SUMMARY→EXPLAIN→PUSH。

    ws_broadcaster: 可選 async function，用於推播 decision.task_update.v1
    讓前端 Agent 活動面板即時顯示每一步的進度。

    [2026-08-01 修正：這個函式原本會凍結整個伺服器約 15~30 秒]
    ---------------------------------------------------------
    本函式是 `async def`，但**只有 A2 規劃器**用了 `asyncio.to_thread`，其餘
    全是同步阻塞呼叫，直接霸佔 event loop：

        GATEWAY.load_data()          ~100ms
        GATEWAY.evaluate_rules()     ~50ms
        GATEWAY.plan_routes()        ~200ms
        GATEWAY.calculate_ete()      ~50ms
        GATEWAY.generate_report()    **~15~20 秒（Bedrock）**
        generate_report_explanation()  ~5~10 秒（Bedrock）

    後果：注入事件後模擬時鐘（`main.py::_simulation_tick_loop` 的
    `await asyncio.sleep(1)`）整段排不到執行，畫面看起來像當掉，直到建議書
    生成完才恢復——這正是實際回報的症狀。WebSocket 推播同樣塞住，所以
    `report_started` 與 `report_done` 之間 20 秒完全靜默。

    現在全部包進 `asyncio.to_thread`。決定性運算雖然只有毫秒級，一併搬過去是
    為了讓「這個函式裡沒有任何同步阻塞」成為可以一眼檢查的性質，而不是每次
    加新步驟都要重新判斷「這個夠不夠快，要不要包」。ContextVar 由
    `asyncio.to_thread` 自動複製，不需額外處理。
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
    bundle = await asyncio.to_thread(GATEWAY.load_data)
    _STATE.active_incidents[event.event_id] = IncidentRecord(
        trace_id=trace_id,
        incident=event,
        bundle_snapshot=bundle,
    )

    # --- 2. FLAGS ---
    sensing = await asyncio.to_thread(GATEWAY.evaluate_rules, bundle, event)
    if sensing.multilingual_required:
        _STATE.multilingual = True
    try:
        record_step(trace_id, "A2", "SET_FLAG", {"multilingual": _STATE.multilingual}, {})
    except Exception as e:
        logger.warning(f"record_step SET_FLAG 失敗: {e}")

    # --- 3. PLAN ---
    # SPEC-O2 §3：事件注入走 A2 LLM 規劃器。規劃器「只規劃、不執行」，這裡拿到的
    # 是工具序列而非計算結果；三層護欄（白名單／必要步驟／8s逾時）都在規劃器內部
    # 完成，任一層失敗回傳 degraded=True，本層據此改走靜態鏈（SPEC-O2 §3.2）。
    requires_rerouting = classification["requires_rerouting"]

    from src.agent.a2_orchestrator_agent import plan_tools

    # 規劃器是同步阻塞呼叫（Strands Agent），丟到工作執行緒才不會卡住 event loop
    # 與 WebSocket 推播。
    plan_result = await asyncio.to_thread(
        plan_tools,
        event_id=event.event_id,
        event_type=event.type,
        classification=classification,
        traffic_level=sensing.traffic_level,
    )

    static_chain = static_chain_for_classification(
        classification, multilingual=_STATE.multilingual
    )

    if plan_result.degraded:
        planned_tools = static_chain
        plan_input = {
            "event_id": event.event_id,
            "classification": classification,
            "degraded": True,
            "reason": plan_result.reason,
        }
        plan_output = {
            "planned_by": "static_dispatch",
            "tools": [t.value for t in static_chain],
        }
    else:
        planned_tools = plan_result.plan.tool_names()
        plan_input = {
            "event_id": event.event_id,
            "classification": classification,
            "degraded": False,
        }
        # SPEC-O2 §3.3：LLM 的規劃決策本身入 Trace，是模組四「A2 這次選了哪些
        # 工具」的資料來源（F7 決策依據面板）。
        plan_output = {
            "planned_by": "a2_llm",
            "tools": plan_result.tool_sequence,
        }

    try:
        record_step(trace_id, "A2", "PLAN", plan_input, plan_output)
    except Exception as e:
        logger.warning(f"record_step PLAN 失敗: {e}")

    # --- 4. EXECUTE ---
    # 依 planned_tools 執行。LLM 已經不再自己呼叫工具，所以這裡是唯一的執行點，
    # 不會出現「規劃器算一次、orchestrator 再算一次」的重複計算。
    planned = set(planned_tools)
    route_plan: RoutePlan | None = None
    ete: EteEstimate | None = None
    report_text: str | None = None
    notification: Notification | None = None
    degraded: list[str] = []
    _dispatch_seq = 0

    if ToolName.ROUTE_SELECT in planned and requires_rerouting:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_started")
        try:
            route_plan = await asyncio.to_thread(
                GATEWAY.plan_routes,
                RouteRequest(incident=event, bundle=bundle, as_of=event.timestamp),
            )
        except Exception as e:
            logger.warning(f"plan_routes 失敗: {e}")
            degraded.append("ROUTING_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_done")

    if ToolName.COUNT_INTERSECTIONS in planned:
        # SOP-5：警力 = 受影響路口數 × 2（SPEC-O2 §2）。歸屬 routing.py，
        # ActorCode 用 R2（路網拓樸判定），與 SPEC-O1 §5「agent 欄位標示執行者」一致。
        try:
            intersections = await asyncio.to_thread(GATEWAY.count_intersections, event, bundle)
            record_step(
                trace_id,
                "R2",
                "TOOL_CALL",
                {"event_id": event.event_id},
                {"intersection_count": intersections, "police_required": intersections * 2},
                tool=ToolName.COUNT_INTERSECTIONS.value,
                sop_ref="SOP-5",
            )
        except Exception as e:
            logger.warning(f"count_intersections 失敗: {e}")

    if ToolName.CALC_ETE in planned:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_started")
        try:
            ete = await asyncio.to_thread(GATEWAY.calculate_ete, event, bundle)
        except Exception as e:
            logger.warning(f"calculate_ete 失敗: {e}")
            degraded.append("ETE_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_done")

    # 安全網：即使規劃器（或靜態鏈）漏了必要工具，決定性模組仍補位。
    # 護欄②理論上已擋掉這種計畫，這裡是最後一道防線，確保 DecisionResult 欄位齊備。
    if requires_rerouting and route_plan is None and "ROUTING_FAILED" not in degraded:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_started")
        try:
            route_plan = await asyncio.to_thread(
                GATEWAY.plan_routes,
                RouteRequest(incident=event, bundle=bundle, as_of=event.timestamp),
            )
        except Exception as e:
            logger.warning(f"plan_routes 失敗: {e}")
            degraded.append("ROUTING_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "routing_done")

    # ETE（所有事件必須有；SPEC-O2 §3.2 護欄②已強制 §2 事件含 CALC_ETE，
    # 這裡涵蓋的是靜態鏈以外、條款未列必要步驟的事件類型）
    if ete is None and "ETE_FAILED" not in degraded:
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_started")
        try:
            ete = await asyncio.to_thread(GATEWAY.calculate_ete, event, bundle)
        except Exception as e:
            logger.warning(f"calculate_ete 失敗: {e}")
            degraded.append("ETE_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "ete_done")

    # [2026-08-01 移除：決策週期不再呼叫 GATEWAY.run_agent()]
    #
    # 這裡原本會呼叫 W1 Agent 取得 `BedrockAdvisory`。移除的理由是實測結果：
    #
    #   1. **產出物沒有任何消費者。** `advisory` 在整個 repo 裡只被當參數傳遞，
    #      沒有一行程式讀取它——`reporting.generate_report()` 的簽章收了這個參數
    #      但函式內部從未使用（`_generate_with_llm` 與 `_generate_c1_c3_fallback`
    #      都不接受它），`DecisionResult` 也沒有對應欄位，前端拿不到、Trace 不記。
    #   2. **成本是每個決策週期 31.6 秒。** 實測一次呼叫要跑 4 輪 tool-call 往返
    #      （query_sop ×3 + simulate_scenario ×1），佔掉雲端整輪 67 秒的將近一半。
    #   3. **失敗一直是靜默的。** `LiveGateway.run_agent` 內部 `except Exception:
    #      return self._stub.run_agent(...)` 把例外吃掉，連 log 都沒有，所以
    #      「花了 31 秒、逾時失敗、結果沒人用」這件事從來沒有人察覺。
    #
    # `LiveGateway.run_agent()` 本身保留（`ModuleGateway` 協定的一部分，
    # `StubGateway` 也實作了它），只是決策週期不再呼叫。要恢復的話把下面這行
    # 換回 `advisory = GATEWAY.run_agent(event, sensing, route_plan, ete)` 即可。
    #
    # 注意：W1 Agent 本身完全沒有被停用——`POST /api/what-if` 的 What-if 對話
    # 走的是 `handle_user_query()` → `process_whatif_request()`，跟這裡無關。
    advisory: BedrockAdvisory | None = None

    # 報告生成
    if ete is not None:
        _dispatch_seq += 1
        # 這一則帶 eta_seconds=20，前端據此畫進度條——這是整個週期唯一會讓
        # 使用者等到懷疑系統當掉的階段（見 _TASK_ETA_SECONDS）。
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "report_started")
        try:
            report_text, notification = await asyncio.to_thread(
                GATEWAY.generate_report, event, sensing, route_plan, ete, advisory, bundle
            )
        except Exception as e:
            logger.warning(f"generate_report 失敗: {e}")
        if report_text is None:
            degraded.append("C1_FAILED")
        if notification is None and _STATE.multilingual:
            degraded.append("C4_FAILED")
        _dispatch_seq += 1
        await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "report_done")

    # 路網規劃結果留痕。放在 EXECUTE 之後、SUMMARY 之前——兩次 plan_routes
    # （主路徑與安全網）不管走哪一條，到這裡 route_plan 都是最終值，只記一次。
    _record_route_plan_step(trace_id, event, route_plan)

    # 二階效應推演：這個決策執行後接下來會出什麼問題。純確定性運算（毫秒級），
    # 不包 to_thread。失敗只是少一段內容，不影響決策本身。
    projected_risks = None
    if ete is not None:
        try:
            from src.risk_projection import project_risks, projection_to_dict

            projected_risks = projection_to_dict(
                project_risks(event, route_plan, sensing, bundle, ete.minutes)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"風險推演失敗: {e}")

    # --- 5. SUMMARY ---
    elapsed = int((time.perf_counter() - start) * 1000)
    try:
        record_step(trace_id, "A2", "CYCLE_SUMMARY", {},
                    {"duration_ms": elapsed},
                    subject_segment_ids=[event.affected_segment] if event.affected_segment.startswith("RD_") else [])
    except Exception as e:
        logger.warning(f"record_step CYCLE_SUMMARY 失敗: {e}")

    # --- 6. EXPLAIN ---
    _dispatch_seq += 1
    await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "explain_started")
    try:
        from src.decision_trace import generate_report_explanation
        # 又一個 Bedrock 呼叫（~5~10 秒）。不包 to_thread 的話，前面辛苦解掉的
        # 阻塞會在最後一步再犯一次。
        await asyncio.to_thread(generate_report_explanation, trace_id)
    except Exception as e:
        logger.warning(f"generate_report_explanation 失敗（降級）: {e}")
    _dispatch_seq += 1
    await _broadcast_task_update(ws_broadcaster, trace_id, _dispatch_seq, "explain_done")

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
        projected_risks=projected_risks,
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


_TRACE_DEAD_ENDS = ("無法識別", "有多種可能")
"""`answer_trace_query()` 的「問不出東西」固定回覆特徵。

這三句是 SPEC-M4B §4 明訂的契約（`tests/test_decision_trace.py` 也鎖著），
不能改那個函式。但**路由層**可以決定「既然回溯答不出來，就換一條路問」——
判斷放在這裡而不是改 `decision_trace.py`，兩邊職責才不會混。
"""


def _attach_trace(response, trace_id: str | None):
    """把決策軌跡掛到對話回覆上（就地修改並回傳）。

    [2026-08-01 新增] 使用者反映「chatbot 的回答沒有顯示決策軌跡」。原因是軌跡
    從來沒有離開過後端記憶體：`decision_trace` 只被 M4B 生成層讀，`W1Response`
    沒有對應欄位，前端自然畫不出來。

    掛在**所有**帶 trace_id 的回覆上，不只回溯分支——使用者問完 What-if 之後
    同樣會想知道「那正式決策當初是怎麼判的」，而那份軌跡就在手邊。

    取不到軌跡（trace 不存在、伺服器重啟過）只是少一塊內容，絕不能中斷回覆。
    """
    if trace_id is None:
        return response

    try:
        from src.decision_trace import get_trace_view

        view = get_trace_view(trace_id)
        if view:
            response.trace_id = trace_id
            response.trace_steps = view["steps"]
    except Exception:  # noqa: BLE001
        logger.debug("取得決策軌跡失敗，回覆不帶軌跡", exc_info=True)

    # 風險推演直接沿用該週期已經算好的那一份，不重算——重算會得到同樣的結果
    # （純函式），但兩份輸出若因為任何原因出現差異，使用者會同時看到兩張
    # 不一致的圖，那比沒有圖更糟。
    try:
        for rec in _STATE.active_incidents.values():
            if rec.trace_id == trace_id and rec.decision_result is not None:
                response.projected_risks = rec.decision_result.projected_risks
                break
    except Exception:  # noqa: BLE001
        logger.debug("取得風險推演失敗，回覆不帶推演", exc_info=True)

    return response


def _trace_answer_payload(trace_id: str | None, answer_text: str):
    """把回溯追問的答案包成跟 W1 一樣的 `W1Response` 形狀。

    [2026-08-01 修正：三分支 payload 形狀不一致造成前端整片空白]
    ------------------------------------------------------------
    原本這一支回的是 `{"trace_id": ..., "answer_text": ...}`，而前端
    `chat-app.js::sendMessage()` 一律用 `renderAIResponse(data.payload)`，
    該函式讀的是 **`data.summary`**（`chat-render.js` 第 27 行）。欄位名對不上
    → `renderMarkdown(undefined || "")` → **完全空白的 AI 泡泡**，連建議問題
    都沒有（`suggested_questions` 這個 key 根本不存在）。

    使用者的體感是「chatbot 死了」——只要問題不含「如果」，不管問什麼都得到
    一個空白氣泡。這不是模型答不出來，是回傳的東西前端讀不到。

    現在三支路由一律回 `W1Response`，前端不需要為分支寫任何 if。
    """
    from src.agent.response_formatter import W1Response
    from src.agent.system_prompt import DEFAULT_QUESTIONS

    return _attach_trace(
        W1Response(
            intent_type="trace_answer",
            summary=answer_text,
            suggested_questions=list(DEFAULT_QUESTIONS),
            source_mode="full",
            tools_called=["answer_trace_query"],
        ),
        trace_id,
    )


def handle_user_query(
    question: str,
    current_trace_id: str | None,
    session_id: str,
    correlation_id: str,
    ws_broadcaster=None,
) -> dict:
    """前端對話入口，對應 REST POST /api/what-if（[2026-07-28更正] SPEC-O3 原寫
    /api/chat，已改為固定端點名）。

    [2026-08-01 路由改寫：從「三分支」改成「一個快篩 + 預設進 Agent」]
    ----------------------------------------------------------------
    原本的規則是 SPEC-O3 §4 的三分支：含前瞻詞 → W1、有 trace_id → 回溯、
    其餘 → 一句固定文字。實際使用下來，第三支等於一道牆：

    - 「台北市有幾條捷運線」→ 沒有「如果」→ 固定文字
    - 「為什麼判 A 級」→ 有 trace_id 但 `resolve_segment_id` 解析不到路段
      → 「無法識別問題中提及的路段」
    - 「今天天氣如何」→ 固定文字

    三種都是死路，而且因為 payload 形狀不對，前端連那句固定文字都顯示不出來
    （見 `_trace_answer_payload()` 的說明）。

    問題出在「必須含『如果』才准進 W1」這條前提本身。W1 Agent 手上就有
    `query_sop` 與 `simulate_scenario` 兩個工具，**該不該查 SOP、該不該重算，
    模型自己判斷得出來**——用關鍵字先替它決定，只會把它能答的問題擋在門外。

    改成：
      1. 非前瞻問題 + 有 trace_id + 問題裡解析得到具體路段 → 回溯追問（M4B
         讀真實決策紀錄，比 Agent 重新推論可靠，這一支保留）
      2. 其餘一律進 W1 Agent

    `_current_trace_ctx` 現在**一律設定**（原本只有前瞻分支設）。這樣 W1 在
    回答任何問題時都拿得到當前決策週期的事實區塊（`build_cycle_facts_block()`），
    「為什麼判 A 級」這種問題它答得出來，因為等級、ETE、命中條款都在事實裡。

    `ws_broadcaster` 轉傳給 `process_whatif_request()` 供 loading 推播。
    """
    from src.agent.whatif_agent import process_whatif_request
    from src.decision_trace import answer_trace_query, resolve_segment_id

    # 一律設定：W1 靠這個 ContextVar 找到使用者正在看的決策週期，
    # 沒設的話 `simulate_scenario` 拿不到 incident，路線與 ETE 全部算不出來。
    _current_trace_ctx.set(current_trace_id)

    is_forward_looking = any(word in question for word in _FORWARD_LOOKING_WORDS)

    if not is_forward_looking and current_trace_id is not None:
        # 回溯追問只在「問題明確指向某個路段」時才走——這是 M4B 的能力邊界
        # （它的檢索鍵就是 segment_id）。解析不到就別硬送，那只會得到
        # 「無法識別問題中提及的路段」這種對使用者毫無用處的回覆。
        resolved = resolve_segment_id(question)
        if resolved not in ("NOT_FOUND", "AMBIGUOUS"):
            answer_text = answer_trace_query(current_trace_id, question)
            if not any(dead in answer_text for dead in _TRACE_DEAD_ENDS):
                return {
                    "message_type": "trace.answered.v1",
                    "payload": _trace_answer_payload(current_trace_id, answer_text),
                }
            # 落到下面走 W1——回溯答不出來不代表沒人答得出來

    result = process_whatif_request(
        session_id=session_id,
        content=question,
        correlation_id=correlation_id,
        ws_broadcaster=ws_broadcaster,
    )
    # W1 的回覆同樣掛上軌跡：使用者問完假設情境之後，緊接著想知道「那正式決策
    # 當初是怎麼判的」是很自然的，軌跡就在手邊沒理由不給。
    _attach_trace(result, current_trace_id)
    return {"message_type": "whatif.evaluated.v1", "payload": result}


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

    # 更新 decision_result 的 routes
    old_decision = record.decision_result
    new_decision = DecisionResult(
        trace_id=old_decision.trace_id,
        triggered_by=old_decision.triggered_by,
        level=old_decision.level,
        incident=old_decision.incident,
        routes=new_route_plan,
        ete=old_decision.ete,
        control_center_report=old_decision.control_center_report,
        notifications=old_decision.notifications,
        degraded=old_decision.degraded,
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
