"""What-if 覆寫重算引擎。[2026-07-28總架構師補充：業界通用版原型]

這是先前標記為「待整合缺口」的部分——`agent/tools.py` 的 `simulate_scenario`
需要一個「帶 assumptions 覆寫、重新跑一次感知+路網+ETE」的入口，但 routing.py/
rules.py/reporting.py 都沒有定義過這樣的函式。

**設計決策（業界標準做法：覆寫資料，重用既有純函式，不要另開一套「_with_overrides」
版本的 evaluate_rules/plan_route/calculate_ete）**：
- 對 `NormalizedDataBundle` 做深拷貝，把 `ScenarioOverrides` 套用上去（改資料，不改邏輯）
- 拿套用覆寫後的 bundle，原封不動呼叫 `rules.evaluate_rules()`／`routing.plan_route()`／
  `reporting.calculate_ete()`——這三個函式完全不需要知道自己是被 What-if 呼叫還是
  正常事件流程呼叫，維持「純函式只認資料、不認呼叫情境」的單一職責原則。
- 原始 `data/` 檔案與正式決策軌跡完全不受影響（`ScenarioOverrides` 只作用在記憶體副本）。

這個模組本身不屬於 M1/M2/M4 任何一個既有 owner，是 M3 What-if 功能專屬的膠合層，
不與其他模組的所有權衝突（`01-module-boundaries.md` 沒有規則說 M3 不能寫一個
自己專用的重算膠合函式，只要不重新實作 R1-R5/ETE 公式本身）。
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from src.models import (
    EteEstimate,
    Incident,
    IncidentSeverity,
    NormalizedDataBundle,
    RouteRequest,
    RoutePlan,
    RuleHit,
    ScenarioOverrides,
    SensingResult,
)

logger = logging.getLogger(__name__)


CROWD_FIELD_MAP = {
    "User_Count": "user_count",
    "user_count": "user_count",
    "Growth_Rate": "growth_rate",
    "growth_rate": "growth_rate",
    "Roaming_User_Pct": "roaming_user_pct",
    "roaming_user_pct": "roaming_user_pct",
    "Stay_Time_Avg": "stay_time_avg",
    "stay_time_avg": "stay_time_avg",
}

TRAFFIC_FIELD_MAP = {
    "Saturation_Score": "saturation_score",
    "saturation_score": "saturation_score",
    # [2026-08-01] 別名。實測 LLM 會自己縮寫成 `RD_TPE_004.saturation`，覆寫因此
    # 整個失敗、What-if 退化成「決策模組暫時不可用」。這不是模型的錯——工具描述
    # 從來沒告訴它合法欄位有哪些（已一併補上，見 `agent/tools.py`）。
    # 別名只收「語意完全等價、不可能指到別的欄位」的縮寫，不做模糊比對。
    "saturation": "saturation_score",
    "Saturation": "saturation_score",
    "Avg_Speed": "avg_speed",
    "avg_speed": "avg_speed",
    "speed": "avg_speed",
    "Vehicle_Count": "vehicle_count",
    "vehicle_count": "vehicle_count",
    "Lane_Status": "lane_status",
    "lane_status": "lane_status",
    "status": "lane_status",  # "status" 映射到 lane_status（最接近的語意）
}

ROAD_FIELD_MAP = {
    "capacity_vph": "capacity_vph",
    "Capacity_VPH": "capacity_vph",
    "capacity": "capacity_vph",
    "flow_direction": "flow_direction",
    "Flow_Direction": "flow_direction",
}


def supported_fields() -> dict[str, list[str]]:
    """回傳各實體前綴支援的**正規欄位名**（去掉別名後的代表名）。

    給 `agent/tools.py` 組工具描述用——工具描述必須跟這裡同源，不能各寫一份，
    否則描述與實作漂移後 LLM 又會開始猜欄位名。
    """
    return {
        "BS_": sorted({v for v in CROWD_FIELD_MAP.values()}),
        "RD_": sorted({v for v in TRAFFIC_FIELD_MAP.values()} | {v for v in ROAD_FIELD_MAP.values()}),
    }


def resolve_entity(bundle: NormalizedDataBundle, token: str) -> str:
    """把使用者／LLM 給的實體代號或名稱，解析成正規的 segment_id／station_id。

    為什麼需要這個
    --------------
    [2026-08-01] 實測災難：使用者問「如果**仁愛路**坍塌會怎樣」，LLM 送出的是
    `RD_TPE_002.lane_status`——但 RD_TPE_002 是**光復南路**，仁愛路四段是
    RD_TPE_005。系統對錯誤的路段跑完整套推演（改道、ETE、風險），然後用完全
    肯定的語氣回答「仁愛路（RD_TPE_002）坍塌封閉後…」。

    使用者問 A，系統算 B，答案講得像 A。這比算不出來危險得多——算不出來會被
    發現，算錯不會。

    根因是工具說明只寫「RD_TPE_001 ~ RD_TPE_015」，**從來沒告訴模型哪個號碼
    對應哪條路**，它只能猜。兩道防線一起上：
      1. 這個函式讓名稱也能用（模型送「仁愛路」也對）
      2. 工具說明列出完整對照表（模型一開始就不必猜）

    比對順序：正規 ID → 完整名稱 → 去掉「一段/二段/四段」後的路名 → 名稱包含關係。
    解析不出來時拋 ValueError 並附上完整清單——寧可讓模型收到錯誤重試，
    也不要默默挑一個最像的然後算錯。
    """
    if not token:
        raise ValueError("實體代號不得為空")

    segments = {s.segment_id: (s.name or "") for s in bundle.road_network}
    stations = sorted({c.station_id for c in bundle.crowd})

    # 1. 正規 ID（最常見的路徑，直接命中）
    if token in segments or token in stations:
        return token

    # 2/3/4. 名稱比對（只對路段做——基站沒有中文名可對）
    stripped = re.sub(r"[一二三四五六七八九十]段$", "", token)
    exact = [sid for sid, name in segments.items() if name == token]
    if len(exact) == 1:
        return exact[0]

    trimmed = [
        sid for sid, name in segments.items()
        if re.sub(r"[一二三四五六七八九十]段$", "", name) == stripped
    ]
    if len(trimmed) == 1:
        return trimmed[0]

    partial = [sid for sid, name in segments.items() if name and (token in name or name in token)]
    if len(partial) == 1:
        return partial[0]

    roster = "、".join(f"{sid}={name}" for sid, name in segments.items())
    if len(partial) > 1:
        raise ValueError(
            f"「{token}」對應到多條路段（{'、'.join(f'{s}={segments[s]}' for s in partial)}），"
            f"請改用明確的 segment_id。完整對照：{roster}"
        )
    raise ValueError(
        f"找不到「{token}」。可用路段對照：{roster}；可用基站：{'、'.join(stations)}"
    )


def normalize_overrides(
    bundle: NormalizedDataBundle, overrides: dict[str, float | int | str]
) -> dict[str, float | int | str]:
    """把 overrides 的 key 從「可能是名稱」正規化成 ID。見 `resolve_entity()`。"""
    normalized: dict[str, float | int | str] = {}
    for key, value in overrides.items():
        entity, sep, field = key.partition(".")
        if not sep:
            normalized[key] = value
            continue
        normalized[f"{resolve_entity(bundle, entity)}.{field}"] = value
    return normalized


def apply_scenario_overrides(
    bundle: NormalizedDataBundle, overrides: dict[str, float | int | str]
) -> NormalizedDataBundle:
    """深拷貝 bundle，依 overrides（key格式 "{entity}.{field}"）覆寫對應欄位。

    entity 前綴 BS_ → 覆寫 CrowdSample（找 station_id 匹配的全部紀錄）
    entity 前綴 RD_ → 覆寫 TrafficSample（找 segment_id 匹配的全部紀錄）
                      或 RoadSegment（如果欄位屬於 RoadSegment）

    找不到對應 entity 或欄位時拋 ValueError，**訊息一律附上合法欄位清單**——
    這個例外會被 `agent/tools.py::simulate_scenario` 包成工具錯誤回給 LLM，
    只寫「不支援的欄位: saturation」它無從自我修正，附上清單它下一輪就會改對。
    """
    new_bundle = copy.deepcopy(bundle)

    _CROWD_FIELD_MAP = CROWD_FIELD_MAP
    _TRAFFIC_FIELD_MAP = TRAFFIC_FIELD_MAP
    _ROAD_FIELD_MAP = ROAD_FIELD_MAP

    for key, value in overrides.items():
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"override key 格式不合法（需 entity.field）: {key}")
        entity, field = parts

        if entity.startswith("BS_"):
            # 覆寫 CrowdSample
            normalized_field = _CROWD_FIELD_MAP.get(field)
            if normalized_field is None:
                raise ValueError(
                    f"BS_ entity 不支援的欄位: {field}。"
                    f"合法欄位：{', '.join(supported_fields()['BS_'])}"
                )
            matched = [c for c in new_bundle.crowd if c.station_id == entity]
            if not matched:
                raise ValueError(f"找不到 station_id={entity} 的 CrowdSample")
            for sample in matched:
                setattr(sample, normalized_field, value)

        elif entity.startswith("RD_"):
            # 先嘗試 TrafficSample
            normalized_field = _TRAFFIC_FIELD_MAP.get(field)
            if normalized_field is not None:
                matched = [t for t in new_bundle.traffic if t.segment_id == entity]
                if not matched:
                    raise ValueError(f"找不到 segment_id={entity} 的 TrafficSample")
                for sample in matched:
                    setattr(sample, normalized_field, value)
            else:
                # 嘗試 RoadSegment
                normalized_field = _ROAD_FIELD_MAP.get(field)
                if normalized_field is not None:
                    matched = [s for s in new_bundle.road_network if s.segment_id == entity]
                    if not matched:
                        raise ValueError(f"找不到 segment_id={entity} 的 RoadSegment")
                    for seg in matched:
                        setattr(seg, normalized_field, value)
                else:
                    raise ValueError(
                        f"RD_ entity 不支援的欄位: {field}。"
                        f"合法欄位：{', '.join(supported_fields()['RD_'])}"
                    )
        else:
            raise ValueError(f"不支援的 entity 前綴（需 BS_ 或 RD_）: {entity}")

    return new_bundle


def run_scenario(
    bundle: NormalizedDataBundle,
    incident: Incident | None,
    overrides: dict[str, float | int | str],
    gateway,  # ModuleGateway，型別放在 src.orchestrator，這裡不直接 import 避免循環依賴
    question: str = "",
) -> dict:
    """套用覆寫後，依序呼叫既有的 evaluate_rules → plan_route → calculate_ete，
    組成 simulate_scenario() 要回傳給 W1 Agent 的結構化結果。

    [2026-07-28總架構師補充：架構完整性修正] 一律透過呼叫端傳入的 `gateway`
    （`src.orchestrator.GATEWAY`）存取 M1/M2/M4，不直接 `from src.rules import
    evaluate_rules` ——理由跟 `orchestrator.py` 的補註一致：維持 Stub/Live
    切換機制在整個系統內一致，What-if 路徑不應該是唯一繞過 Gateway 的例外。

    [2026-07-28再補充：回應Kiro審查] `incident` 可以是 `None`——使用者問
    「如果BL17到40000」這類問題時，如果前端沒有帶 `current_trace_id`（沒有正在
    查看特定事件），就沒有 incident 可用。這時只做 `evaluate_rules`（P1-P5 本來就
    支援 `incident=None`），`route_plan`/`ete` 留 `None`，因為 `plan_routes`/
    `calculate_ete` 兩者都需要 incident 才有意義（路線跟ETE都是「某個事故」的
    路線/恢復時間，沒有事故就沒有這兩個問題）。

    不寫決策軌跡（What-if 不留痕，SPEC-00 §4 慣例）、不改動原始 bundle。

    [2026-08-01 修正：回傳值必須是 JSON 相容的純 dict]
    這個函式的回傳值會直接成為 Strands `@tool simulate_scenario` 的輸出，而
    Strands 會把工具結果 `json.dumps` 後放進 toolResult 送回模型。原本這裡直接
    回傳 `RuleHit`／`RoutePlan`／`EteEstimate`（全部是 Pydantic BaseModel），
    `json.dumps` 會拋 `TypeError: Object of type RoutePlan is not JSON serializable`
    ——也就是說 What-if 模擬的結果**從來沒有真的送達過模型**。

    改用 `model_dump(mode="json")` 轉換（`mode="json"` 是必要的，預設 mode 會留下
    `datetime` 與 `Enum` 物件，一樣不能序列化）。

    同時補上兩個原本掛 TODO 的欄位：`judgment_basis`（人話判斷依據）與
    `current_data_snapshot`（覆寫後的關鍵數值），兩者都是 `W1Response` 已宣告
    但永遠拿不到值的欄位。
    """
    # 先把路名正規化成 ID。模型送「仁愛路.lane_status」也要能算對——
    # 見 `resolve_entity()`：它曾經把仁愛路當成 RD_TPE_002（光復南路）。
    overrides = normalize_overrides(bundle, overrides)

    # [2026-08-01] 封閉假設 → 合成假想事故，讓整條「推演 → 解方」鏈跑起來。
    # 理由見 `synthesize_incident()`：不補這一步，使用者的封閉假設對規則引擎
    # 完全空轉，畫面上只會出現一堆與問題無關的背景命中。
    if incident is None:
        targets = closure_targets(overrides)
        if targets:
            return _closure_scenarios(bundle, targets[0], overrides, gateway, question)

    outcome = compute_scenario(bundle, incident, overrides, gateway)
    result = scenario_to_dict(outcome, overrides, incident)
    result["risk_projection"] = _project_for(outcome, incident)
    return result


def _project_for(outcome: ScenarioOutcome, incident: Incident | None) -> dict | None:
    """對一個情境跑二階風險推演。失敗回 None——少一段內容，不中斷回答。"""
    if incident is None or outcome.route_plan is None or outcome.ete is None:
        return None
    try:
        from src.risk_projection import project_risks, projection_to_dict

        return projection_to_dict(
            project_risks(
                incident, outcome.route_plan, outcome.sensing, outcome.bundle, outcome.ete.minutes
            )
        )
    except Exception:  # noqa: BLE001
        logger.warning("What-if 風險推演失敗", exc_info=True)
        return None


def _closure_scenarios(
    bundle: NormalizedDataBundle,
    segment_id: str,
    overrides: dict[str, float | int | str],
    gateway,
    question: str,
) -> dict:
    """「如果某條路封閉」的完整回答。

    嚴重度處理（使用者選定的方案 C）：
      - 問題裡講明了（「嚴重車禍」「輕微擦撞」）→ 只算那一種
      - 沒講 → **三種都算並列**，讓指揮官看著差異自己挑

    為什麼是並列而不是回問一句：ETE 在 Critical/High/Medium 之間差到 40 分鐘
    （SOP-7 base_clearance 60/40/20），那個差距會直接改變調度決策。與其猜一個
    使用者沒同意過的值、或是丟一個問題回去讓他再等一輪，不如把三種後果攤開，
    他掃一眼就知道自己面對的是哪一種。
    """
    as_of, as_of_reason = resolve_scenario_as_of(bundle, None)
    stated = detect_severity(question)
    severities = [stated] if stated else list(SEVERITY_LADDER)

    scenarios = []
    for severity in severities:
        hypothetical = synthesize_incident(bundle, segment_id, severity, as_of)
        outcome = compute_scenario(bundle, hypothetical, overrides, gateway)
        detail = scenario_to_dict(outcome, overrides, hypothetical)
        detail["severity"] = severity
        detail["severity_label"] = _SEVERITY_LABELS[severity]
        detail["risk_projection"] = _project_for(outcome, hypothetical)
        scenarios.append(detail)

    primary = scenarios[0]
    name = next(
        (s.name for s in bundle.road_network if s.segment_id == segment_id), segment_id
    )

    result = dict(primary)
    result["hypothetical_incident"] = {
        "segment_id": segment_id,
        "segment_name": name,
        "as_of": as_of.strftime("%H:%M"),
        "as_of_reason": as_of_reason,
        "severity_stated": stated is not None,
    }
    # 只有在使用者沒指定嚴重度時才給比較表——指定了就沒有選項要挑。
    if stated is None:
        result["severity_options"] = [
            {
                "severity": s["severity"],
                "severity_label": s["severity_label"],
                "ete_minutes": (s.get("ete") or {}).get("minutes"),
                "recovery_at": (s.get("ete") or {}).get("recovery_at"),
                "primary_route": ((s.get("route_plan") or {}).get("primary") or {}).get("name"),
                "risk_count": len(((s.get("risk_projection") or {}).get("risks")) or []),
                "first_risk_at": (
                    (((s.get("risk_projection") or {}).get("risks")) or [{}])[0].get("at_time")
                ),
                "no_safe_route": (s.get("risk_projection") or {}).get("no_safe_route", False),
            }
            for s in scenarios
        ]
    return result


@dataclass
class ScenarioOutcome:
    """`compute_scenario()` 的物件版輸出。

    為什麼要跟 `run_scenario()` 的 dict 版分開：`run_scenario()` 的回傳值會被
    Strands `json.dumps` 送回模型，**不能夾帶 Pydantic 物件**。但方案B 的情境
    建議書又必須拿到物件才能餵給 `reporting.generate_report()`。

    做法是拆兩層，而不是在 dict 裡偷藏一個底線開頭的 key——後者遲早會有人
    忘記剝掉然後在雲端炸序列化。物件層與 JSON 層各自單一職責，重算一次的成本
    是純函式運算（沒有 I/O、沒有 LLM），可以忽略。
    """

    sensing: SensingResult
    route_plan: RoutePlan | None
    ete: EteEstimate | None
    bundle: NormalizedDataBundle
    """套用覆寫後的 bundle 副本。原始 bundle 未受影響。"""
    base_bundle: NormalizedDataBundle | None = None
    """覆寫**之前**的 bundle。

    [2026-08-01] 新增。前端的推理鏈要顯示「0.78 ──▶ 0.98」這種改前改後對照，
    少了原值就只能顯示改後的數字——而「飽和度 0.98」單獨看沒有資訊量，
    使用者要看的是「本來多少、動了多少」。

    可為 None（舊呼叫端沒傳時），此時 `build_data_snapshot()` 的 `before`
    欄位一律留 None，前端只顯示改後值，不會壞掉。
    """
    as_of: datetime | None = None
    """本次評估用的時刻。見 `resolve_scenario_as_of()`。"""
    as_of_reason: str | None = None
    """為什麼選這個時刻（「事故發生時刻」／「模擬器當前時刻」／「資料集最新時刻」）。

    一定要跟著結果一起回到畫面上。使用者看到「命中 15 條」時，必須同時看得到
    「評估時刻 23:30（資料集最新時刻）」，否則那 15 條無從理解。
    """


_CLOSURE_STATUSES = ("Closed", "Blocked")
"""哪些 `lane_status` 值算「這條路不能走了」。"""

SEVERITY_LADDER = ("Critical", "High", "Medium")
"""並列比較時的嚴重度階梯，由重到輕。對應 SOP-7 的 base_clearance 60/40/20 分鐘。"""

_SEVERITY_LABELS = {
    "Critical": "重大",
    "High": "嚴重",
    "Medium": "中等",
}

_SEVERITY_KEYWORDS = {
    "Critical": ("重大", "嚴重車禍", "塌陷", "坍塌", "全毀", "災難", "critical"),
    "High": ("嚴重", "重傷", "high"),
    "Medium": ("輕微", "擦撞", "中等", "小事故", "medium", "minor"),
}
"""嚴重度關鍵字。**一律使用兩字以上的詞**。

[2026-08-01] 第一版把「大」放進 High、「小」放進 Medium，結果每個問題都被判成
High——因為「市民**大**道」含「大」。使用者問「如果市民大道四段輕微擦撞封閉」
也一樣被判 High，連「輕微」都沒機會比對到。

單字在中文裡幾乎必然出現在路名或其他無關詞裡。這種比對只會製造出使用者
無法理解、也無從察覺的錯誤——ETE 差 40 分鐘，而畫面上不會有任何跡象顯示
系統誤判了嚴重度。
"""


def detect_severity(question: str) -> str | None:
    """從使用者的措辭判斷嚴重度。判斷不出來回 None（此時應並列三種）。

    刻意只認明確字眼，寧可回 None 讓使用者看三種比較，也不要猜一個然後
    給出一個他沒同意過的 ETE——ETE 差 40 分鐘會直接改變調度決策。
    """
    if not question:
        return None
    lowered = question.lower()
    # 由重到輕比對，「嚴重車禍」要先被 Critical 接走而不是落到 High
    for severity in SEVERITY_LADDER:
        for kw in _SEVERITY_KEYWORDS[severity]:
            if kw in lowered:
                return severity
    return None


def closure_targets(overrides: dict[str, float | int | str]) -> list[str]:
    """挑出「假設某條路不能走」的覆寫對象，回 segment_id 清單。"""
    targets = []
    for key, value in overrides.items():
        entity, _, field = key.partition(".")
        if not entity.startswith("RD_"):
            continue
        if field == "lane_status" and str(value) in _CLOSURE_STATUSES:
            targets.append(entity)
    return targets


def synthesize_incident(
    bundle: NormalizedDataBundle,
    segment_id: str,
    severity: str,
    as_of: datetime,
) -> Incident:
    """把「假設這條路封閉」變成一起假想事故。

    為什麼需要這個
    --------------
    [2026-08-01] 實測發現使用者的封閉假設**對規則引擎完全沒有作用**：

        SOP-1  只看 saturation_score  → 改 lane_status 不影響
        SOP-2  需要一個 Incident 物件  → 沒有事故就不觸發
        SOP-3~7 與路段封閉無關

    所以使用者輸入「如果市民大道四段封閉會怎樣」，規則引擎一條都不會反應，
    畫面上只剩下該時刻全市既有的十幾條背景命中——看起來像系統答非所問，
    實際上是這個假設**空轉**了。

    路線重規劃與 ETE 也拿不到：兩者都需要 incident 才有意義，於是整條
    「推演 → 解方」的鏈在 What-if 路徑上從來沒有跑起來過。

    補上這個合成步驟之後，一句「如果某某路封閉」就能走完整條鏈：
    SOP-2 觸發 → 路線重規劃 → ETE → 二階風險推演 → SOP 對策。

    這是**假想的**事故，不寫入 `active_incidents`、不留決策軌跡（What-if 不留痕，
    SPEC-00 §4），只在這一次計算中存在。`event_id` 前綴 `WHATIF_` 讓它在任何
    輸出裡都一眼可辨，不會被誤認為真實事件。
    """
    name = next(
        (s.name for s in bundle.road_network if s.segment_id == segment_id),
        segment_id,
    )
    return Incident(
        event_id=f"WHATIF_{segment_id}",
        # 用 Road_Collapse_Accident：A1 分類表把它映到 SOP-2 且 requires_rerouting=True，
        # 正是「路不能走了，請規劃改道」這個語意。
        type="Road_Collapse_Accident",
        location=name,
        affected_segment=segment_id,
        affected_road=segment_id,
        status="Closed",
        severity=IncidentSeverity(severity),
        description=f"【假設情境】{name}封閉",
        timestamp=as_of,
    )


def resolve_scenario_as_of(
    bundle: NormalizedDataBundle,
    incident: Incident | None,
) -> tuple[datetime, str]:
    """決定 What-if 要用哪個時刻評估，並回傳選擇理由。

    優先序（由具體到泛用）：
      1. 使用者正在查看的事故時間 —— 他問的就是這起事故的假設情境
      2. 模擬器當前時間 —— 沒有事故但正在跑時間軸，畫面上顯示的就是這個時刻
      3. 資料集最新時間 —— 前兩者都沒有時的保底

    [2026-08-01] 第 2 條是新加的，也是本次修正的重點。原本沒有事故就直接掉到
    第 3 條，於是使用者在模擬器上看著 22:10、開對話框問假設，系統卻拿 23:30
    的資料回答他——那個時刻全市 15 條路段有 10 條飽和，畫面顯示「命中 15 條」
    而使用者完全無法理解那些命中從哪來（因為跟他的假設無關，也跟他看的時間無關）。

    回傳理由字串是刻意的：這個選擇一定要能被使用者看見。任何「系統幫你挑了一個
    你不知道的預設值」都會製造這種無法解釋的畫面。
    """
    if incident is not None:
        return incident.timestamp, "事故發生時刻"

    # 模擬器時間。放在函式內 import：main 是應用層，被 src 反向依賴不理想，
    # 但這裡要的是「使用者畫面上的時間」，那份狀態的唯一來源就是 main。
    # 取不到就往下走，不讓它變成硬相依。
    try:
        from main import get_simulation_time

        sim_time = get_simulation_time()
        if sim_time is not None:
            return sim_time, "模擬器當前時刻"
    except Exception:  # noqa: BLE001
        logger.debug("取不到模擬器時間，改用資料集最新時刻", exc_info=True)

    timestamps = [t.timestamp for t in bundle.traffic] + [c.timestamp for c in bundle.crowd]
    latest = max(timestamps) if timestamps else bundle.loaded_at
    return latest, "資料集最新時刻"


def compute_scenario(
    bundle: NormalizedDataBundle,
    incident: Incident | None,
    overrides: dict[str, float | int | str],
    gateway,
) -> ScenarioOutcome:
    """套用覆寫並重算，回傳物件版結果。`run_scenario()` 與情境建議書共用這一份。"""
    overridden = apply_scenario_overrides(bundle, overrides)
    as_of, as_of_reason = resolve_scenario_as_of(bundle, incident)
    sensing = gateway.evaluate_rules(overridden, incident, as_of)

    route_plan = None
    ete = None
    if incident is not None:
        route_plan = gateway.plan_routes(
            RouteRequest(incident=incident, bundle=overridden, as_of=incident.timestamp)
        )
        ete = gateway.calculate_ete(incident, overridden)

    return ScenarioOutcome(
        sensing=sensing,
        route_plan=route_plan,
        ete=ete,
        bundle=overridden,
        base_bundle=bundle,
        as_of=as_of,
        as_of_reason=as_of_reason,
    )


def scenario_to_dict(
    outcome: ScenarioOutcome,
    overrides: dict[str, float | int | str],
    incident: Incident | None,
) -> dict:
    """把 `ScenarioOutcome` 轉成 JSON 相容 dict（Strands 工具回傳格式）。"""
    return {
        "rule_hits": _json_safe(outcome.sensing.rule_hits),
        "route_plan": _json_safe(outcome.route_plan),
        "ete": _json_safe(outcome.ete),
        "judgment_basis": build_judgment_basis(
            outcome.sensing, outcome.route_plan, outcome.ete, incident
        ),
        # [2026-08-01] 結構化版本的判斷依據，供前端畫推理鏈。
        # `judgment_basis`（字串版）保留不動：LLM 的 prompt 讀的是那一份，
        # 而模型讀連貫文字比讀巢狀 JSON 準確。兩份同源、不會分歧——都是從
        # 同一組 `rule_hits`／`route_plan`／`ete` 拼出來的。
        "judgment_steps": build_judgment_steps(
            outcome.sensing,
            outcome.route_plan,
            outcome.ete,
            outcome.bundle,
            incident,
            # 使用者假設的對象（"RD_TPE_004.lane_status" → "RD_TPE_004"），
            # 供命中條款標記焦點。
            assumption_targets={k.split(".", 1)[0] for k in overrides},
            as_of_reason=outcome.as_of_reason,
        ),
        "current_data_snapshot": build_data_snapshot(
            outcome.bundle, overrides, incident, base=outcome.base_bundle
        ),
        "actions": build_expected_actions(outcome.sensing, outcome.route_plan, outcome.ete),
    }


def _json_safe(obj):
    """Pydantic 物件 → JSON 相容結構。`mode="json"` 會一併處理 datetime 與 Enum。"""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_json_safe(o) for o in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


MAX_LISTED_HITS = 3
"""並行命中最多逐條列出幾個，其餘只給統計。

[2026-08-01] 原本把所有 rule_hits 串成一行，實測 15 條全列會產出這種東西：

    並行命中 — SOP-1：RD_TPE_001 saturation_score = 0.85（門檻 0.85）；SOP-1：
    RD_TPE_002 saturation_score = 0.9（門檻 0.85）；SOP-1：RD_TPE_004 ...
    （再九條）...；SOP-6：BS_XY_VIESHOW roaming_user_pct = 0.3（門檻 0.3）

前端把它當一整段塞進「判斷依據」欄位，畫面上就是一大坨沒有斷點的文字，
沒有人會讀完。判斷依據的用途是讓指揮官三秒內知道「為什麼是這個結論」，
不是稽核用的完整清單——完整清單在決策軌跡（decision_trace）裡本來就有。
"""


def build_judgment_basis(
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate | None,
    incident: Incident | None = None,
) -> str:
    """把命中條款的 `EvidenceRef` 組成人話敘述（原 `judgment_basis` TODO）。

    **這裡只做字串拼接，不做任何判斷或推論**——所有數值、門檻、條款編號都是
    `rules.py` 已經算好寫進 `RuleHit.evidence` 的東西（SPEC-00 鐵律①）。
    寫成 Python 而不是丟給 LLM 生成，正是因為這段文字會被當成「判斷依據」引用，
    不能有任何被改寫的空間。

    輸出以換行分段、並行命中只列前 `MAX_LISTED_HITS` 條（見該常數說明）。
    """
    parts: list[str] = []

    primary = [h for h in sensing.rule_hits if h.is_primary]
    others = [h for h in sensing.rule_hits if not h.is_primary]

    def _hit_text(hit: RuleHit) -> str:
        ev = hit.evidence
        target = hit.segment_id or hit.station_id or ""
        target_text = f"{target} " if target else ""
        if ev.threshold is not None:
            return f"{hit.clause_id}：{target_text}{ev.field} = {ev.value}（門檻 {ev.threshold}）"
        return f"{hit.clause_id}：{target_text}{ev.field} = {ev.value}"

    if primary:
        parts.append("**主因條款**")
        parts.extend(f"- {_hit_text(h)}" for h in primary)

    if others:
        shown = others[:MAX_LISTED_HITS]
        parts.append(f"**並行命中**（{len(others)} 條）")
        parts.extend(f"- {_hit_text(h)}" for h in shown)
        remaining = len(others) - len(shown)
        if remaining > 0:
            # 其餘的只給條款編號統計，讓人知道「還有什麼」但不佔版面。
            #
            # [2026-08-01] 原文是「完整清單見決策軌跡」——那是個**指向不存在
            # 之處的指引**：What-if 重算依 SPEC-00 §4 刻意不留痕，根本沒有對應
            # 的決策軌跡可看；就算是正式週期，軌跡裡也沒有逐條的 rule_hits。
            # 使用者照著找找不到，只會以為系統壞了。
            #
            # 完整清單改由前端就地展開（`judgment_steps` 現在帶全部命中），
            # 這裡是給 LLM 讀的文字，不再給出任何指路。
            rest_clauses = sorted({h.clause_id for h in others[MAX_LISTED_HITS:]})
            parts.append(f"- 另有 {remaining} 條（{', '.join(rest_clauses)}）")

    if not sensing.rule_hits:
        parts.append("此假設情境下沒有任何 SOP 條款被觸發")

    parts.append(f"**交通分級**：{sensing.traffic_level}")

    if route_plan is not None:
        if route_plan.no_feasible_route:
            # 措辭刻意跟風險推演的 `no_safe_route`（「推演後都會飽和」）分開。
            # 兩者一個是現在沒得選、一個是現在有得選但撐不久，混用會誤導處置。
            parts.append("**路網重規劃**：目前無合格替代路線（所有候選都被排除）")
        else:
            if route_plan.primary:
                parts.append(f"**主要替代路線**：{route_plan.primary.name}（{route_plan.primary.segment_id}）")
            if route_plan.secondary:
                parts.append(f"**次要替代路線**：{route_plan.secondary.name}（{route_plan.secondary.segment_id}）")

    if ete is not None:
        parts.append(f"**ETE**：{ete.formula}，預計恢復 {ete.recovery_at}")

    return "\n".join(parts)


_TRAFFIC_SNAPSHOT_FIELDS = ("saturation_score", "avg_speed", "vehicle_count", "lane_status")
_CROWD_SNAPSHOT_FIELDS = ("user_count", "growth_rate", "roaming_user_pct", "stay_time_avg")


def _as_of_sample(samples: list, as_of=None):
    """取 `timestamp <= as_of` 的最近一筆，跟 `rules._as_of_traffic()` 同語意。

    [2026-08-01] 原本寫的是 `max(samples, key=timestamp)`——整份資料的最後一筆，
    不管事故發生在什麼時候。實測 ACC_001（事故時間 22:10）會這樣：

        規則引擎用的值：22:00 那筆（as-of 查詢）
        快照顯示的值　：22:45 那筆（資料集最後一筆）

    也就是推理鏈上顯示的數字，跟決策實際採用的數字**不是同一個**。這種不一致
    在指揮中心情境下比顯示不完整更糟——使用者會拿畫面上的數字去對條款門檻，
    然後發現對不起來。

    `as_of` 為 None 時退回「取最新一筆」（沒有事故就沒有 as-of 基準點，
    此時「現在」就是資料集的末端，這是合理的）。
    """
    if not samples:
        return None
    if as_of is not None:
        candidates = [s for s in samples if s.timestamp <= as_of]
        if candidates:
            return max(candidates, key=lambda s: s.timestamp)
        # as_of 早於所有樣本：退回最早那筆，總比回 None 讓整格空掉好
        return min(samples, key=lambda s: s.timestamp)
    return max(samples, key=lambda s: s.timestamp)


def build_data_snapshot(
    overridden: NormalizedDataBundle,
    overrides: dict[str, float | int | str],
    incident: Incident | None,
    base: NormalizedDataBundle | None = None,
) -> dict:
    """覆寫套用後的關鍵欄位快照（原 `current_data_snapshot` TODO）。

    只回「這次假設真的動到的實體」加上事故路段本身，不是整包 bundle——W1 需要的是
    「你改了什麼、改完長怎樣」，把幾百筆 sample 全塞回去只會灌爆 context window。

    [2026-08-01] 新增 `base` 參數與每個實體的 `before` 區塊。前端推理鏈要畫的是
    「0.78 ──▶ 0.98」的對照，只有改後值畫不出來。`base` 為 None 時 `before`
    留 None，前端會退化成只顯示現值——舊呼叫端不會壞。
    """
    touched_entities = {key.split(".", 1)[0] for key in overrides if "." in key}
    if incident is not None:
        touched_entities.add(incident.affected_segment)
        if incident.affected_road:
            touched_entities.add(incident.affected_road)

    # 決策用的是事故當下的 as-of 值，快照必須用同一個基準點（見 `_as_of_sample`）
    as_of = incident.timestamp if incident is not None else None

    snapshot: dict = {"applied_overrides": dict(overrides), "entities": {}}

    for entity in sorted(touched_entities):
        if entity.startswith("RD_"):
            sample = _as_of_sample(
                [s for s in overridden.traffic if s.segment_id == entity], as_of
            )
            if sample is None:
                continue
            entry = {
                "kind": "traffic",
                "road_name": sample.road_name,
                "snapshot_at": sample.timestamp.isoformat(),
                **{f: getattr(sample, f) for f in _TRAFFIC_SNAPSHOT_FIELDS},
            }
            if base is not None:
                prev = _as_of_sample([s for s in base.traffic if s.segment_id == entity], as_of)
                if prev is not None:
                    entry["before"] = {f: getattr(prev, f) for f in _TRAFFIC_SNAPSHOT_FIELDS}
            snapshot["entities"][entity] = entry

        elif entity.startswith("BS_"):
            sample = _as_of_sample(
                [s for s in overridden.crowd if s.station_id == entity], as_of
            )
            if sample is None:
                continue
            entry = {
                "kind": "crowd",
                "station_name": sample.station_name,
                "snapshot_at": sample.timestamp.isoformat(),
                **{f: getattr(sample, f) for f in _CROWD_SNAPSHOT_FIELDS},
            }
            if base is not None:
                prev = _as_of_sample([s for s in base.crowd if s.station_id == entity], as_of)
                if prev is not None:
                    entry["before"] = {f: getattr(prev, f) for f in _CROWD_SNAPSHOT_FIELDS}
            snapshot["entities"][entity] = entry

    return snapshot


_FIELD_LABELS = {
    "saturation_score": "飽和度",
    "avg_speed": "平均速率",
    "vehicle_count": "車輛數",
    "lane_status": "車道狀態",
    "capacity_vph": "每小時容量",
    "flow_direction": "流向",
    "user_count": "人數",
    "growth_rate": "成長率",
    "roaming_user_pct": "漫遊比率",
    "stay_time_avg": "平均停留",
}
"""欄位機器名 → 中文標籤。前端推理鏈顯示用。

放後端而不是前端：欄位清單的權威來源已經是 `supported_fields()`，標籤跟著
它走才不會出現「後端支援新欄位、畫面顯示英文變數名」的漂移。
"""


def _entity_display_name(bundle: NormalizedDataBundle, entity_id: str) -> str:
    """把 RD_TPE_004 這種代碼換成「市民大道四段」。查不到就回代碼本身。"""
    if entity_id.startswith("RD_"):
        sample = _as_of_sample([s for s in bundle.traffic if s.segment_id == entity_id])
        if sample is not None and sample.road_name:
            return sample.road_name
        for seg in bundle.road_network:
            if seg.segment_id == entity_id and seg.name:
                return seg.name
    elif entity_id.startswith("BS_"):
        sample = _as_of_sample([s for s in bundle.crowd if s.station_id == entity_id])
        if sample is not None and sample.station_name:
            return sample.station_name
    return entity_id


def build_judgment_steps(
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate | None,
    bundle: NormalizedDataBundle,
    incident: Incident | None = None,
    assumption_targets: set[str] | None = None,
    as_of_reason: str | None = None,
) -> list[dict]:
    """`judgment_basis` 的結構化版本，供前端畫推理鏈。

    為什麼要另外做一份而不是讓前端 parse 字串
    ------------------------------------------
    `build_judgment_basis()` 產出的是給 LLM 讀的連貫文字（多行 Markdown）。
    前端原本就是拿那串文字直接 `escapeHtml` 塞進一個小灰字 div，換行與粗體
    全被吃掉，畫面上是一坨沒有斷點的文字——這是實際回報的「內容過於冗長」。

    要畫成圖（門檻比例條、改前改後箭頭、路線變化），前端需要的是**數值本身**，
    不是描述數值的句子。從字串反解會很脆（改一個標點就壞），所以這裡直接輸出
    結構。兩份同源，都只讀 `rule_hits`／`route_plan`／`ete`，不會分歧。

    **這裡一樣只做整理，不做任何判斷或推論**（SPEC-00 鐵律①）。
    """
    steps: list[dict] = []

    # --- 命中條款 ---
    primary = [h for h in sensing.rule_hits if h.is_primary]
    others = [h for h in sensing.rule_hits if not h.is_primary]

    # [2026-08-01] 命中條款分三類——回應「為什麼那麼多命中？」
    #
    # `rules.evaluate_rules()` 掃的是**全市**：SOP-1 逐一比對 15 條路段、
    # SOP-6 逐一比對所有基站。所以「命中 9 條」的意思是「該時刻全市有 9 個地方
    # 跨過 SOP 門檻」，**不是**「這起事故觸發了 9 條規則」。
    #
    # 實測 ACC_001 的 9 條裡，只有 SOP-2 是因這起事故而觸發（is_primary），
    # 其餘 8 條是同一時刻全市各處的背景狀況——忠孝東路壅塞、市政府站人流、
    # 大巨蛋散場、多語通報站點，跟這起路面塌陷沒有因果關係。
    #
    # [2026-08-01 第二次修正] 焦點不只是事故，**也包含使用者自己改的東西**。
    # 第一版只看 `incident.affected_segment`，於是使用者問「如果市民大道四段
    # 封閉會怎樣」而畫面上沒有進行中事故時，`affected_ids` 是空的，15 條命中
    # 全部被標成「全市背景・與本事故無因果關係」——包含使用者剛剛假設的那條路。
    # 那句文案在沒有事故的情境下也根本不成立。
    #
    # What-if 的焦點就是使用者動的那個對象。它應該是主因。
    focus_ids: set[str] = set()
    for key in (assumption_targets or ()):
        focus_ids.add(key)

    affected_ids = set()
    if incident is not None:
        if incident.affected_segment:
            affected_ids.add(incident.affected_segment)
        if incident.affected_road:
            affected_ids.add(incident.affected_road)

    def _relation_of(hit: RuleHit) -> tuple[str, str]:
        target = hit.segment_id or hit.station_id or ""
        # 使用者假設的對象優先於事故——他問的就是「我改了這個會怎樣」，
        # 那條路段上的命中就是他要的答案，不該被降級成背景。
        if target and target in focus_ids:
            return "assumed", "你假設的對象"
        if hit.is_primary:
            return "primary", "主因"
        if target and target in affected_ids:
            return "related", "事故路段連帶"
        return "background", "全市其他地方"

    def _hit_item(hit: RuleHit) -> dict:
        ev = hit.evidence
        target = hit.segment_id or hit.station_id or ""
        relation, relation_label = _relation_of(hit)
        item = {
            "clause_id": hit.clause_id,
            "target": target,
            "target_name": _entity_display_name(bundle, target) if target else "",
            "field": ev.field,
            "field_label": _FIELD_LABELS.get(ev.field, ev.field),
            "value": ev.value,
            "threshold": ev.threshold,
            "is_primary": hit.is_primary,
            "relation": relation,
            "relation_label": relation_label,
        }
        # ratio 讓前端畫「實際值 vs 門檻」的比例條。只有兩邊都是數字時才算得出來
        # （SOP-2 的 evidence 是 "Closed/Critical" 這種字串，沒有比例可言）。
        if isinstance(ev.value, (int, float)) and isinstance(ev.threshold, (int, float)) and ev.threshold:
            item["ratio"] = round(ev.value / ev.threshold, 3)
        return item

    # 排序：假設對象 → 主因 → 事故連帶 → 全市背景，讓使用者最關心的在最上面
    _RELATION_ORDER = {"assumed": 0, "primary": 1, "related": 2, "background": 3}
    ordered = sorted(
        primary + others,
        key=lambda h: _RELATION_ORDER[_relation_of(h)[0]],
    )

    # [2026-08-01] 改成帶**全部**命中，由前端決定摺疊幾條。
    #
    # 原本這裡只送前幾條，其餘用 `hidden_count` 帶個數字，前端顯示「另有 N 條，
    # 完整清單見決策軌跡」——但那份完整清單哪裡都沒有：What-if 依 SPEC-00 §4
    # 刻意不留痕，沒有決策軌跡；正式週期的軌跡裡也沒有逐條 rule_hits。
    # 使用者點進決策軌跡找不到東西。
    #
    # 全部送出去的成本很小（實測最多 15 條、每條是幾個純量欄位），換來的是
    # 前端可以就地展開，不必指向別的地方。
    # [2026-08-01 定案：問答裡不再有「命中條款」]
    # ------------------------------------------------
    # 這一段原本送出全部 rule_hits（實測 9~17 條），前端畫成「命中條款」清單。
    # 使用者連續三輪反映看不懂、覺得沒用，最後結論是砍掉。他是對的，理由：
    #
    # `evaluate_rules()` 掃全市是**為了 Dashboard 的態勢掌握**設計的——F1 KPI
    # 的「目前最高應變等級」就是從 rule_hits 算出來的，值班人員需要知道現在
    # 全市哪裡在燒。那個需求成立。
    #
    # 但它會出現在問答裡，只是因為 What-if 重用了 `evaluate_rules()`，順手把
    # `rule_hits` 一起帶了出來。**沒有人是為了回答使用者的問題而設計它的。**
    # 對「如果仁愛路坍塌會怎樣」這個問題，全市另外 14 個地方超標從來沒有幫
    # 任何人做過決定，它只是把真正重要的那一兩條擠到看不見的地方。
    #
    # 現在只送「適用條款」：決定處置鏈的主因，加上使用者自己假設的對象。
    # 通常 1~3 條。全市掃描結果留在 Dashboard，那裡才是它的位置。
    _RELEVANT = ("assumed", "primary", "related")
    applicable = [h for h in ordered if _relation_of(h)[0] in _RELEVANT]

    steps.append({
        "stage": "rules",
        "title": "適用條款",
        "items": [_hit_item(h) for h in applicable],
        "extra": {
            "traffic_level": sensing.traffic_level,
            "multilingual_required": sensing.multilingual_required,
            # 評估時刻一定要講——同一條路在 22:10 與 23:30 是完全不同的世界
            # （實測市民大道四段 0.78 vs 0.98）。見 resolve_scenario_as_of()。
            "as_of": sensing.as_of.strftime("%H:%M") if sensing.as_of else None,
            "as_of_reason": as_of_reason,
            "has_incident": incident is not None,
            # 使用者假設了某個對象、但它一條規則都沒觸發時，明說。
            # 不講的話畫面會是空的，看起來像系統沒反應。
            "assumed_no_hit": sorted(
                t for t in (assumption_targets or ())
                if not any((h.segment_id or h.station_id) == t for h in ordered)
            ),
        },
    })

    # --- 路線規劃 ---
    if route_plan is not None:
        route_items: list[dict] = []
        for role, candidate in (("primary", route_plan.primary), ("secondary", route_plan.secondary)):
            if candidate is None:
                continue
            route_items.append({
                "role": role,
                "segment_id": candidate.segment_id,
                "name": candidate.name,
                "saturation_score": candidate.saturation_score,
                "capacity_vph": candidate.capacity_vph,
            })
        for exc in route_plan.excluded:
            route_items.append({
                "role": "excluded",
                "segment_id": exc.segment_id,
                "name": exc.name,
                "reason": _reason_code_to_text_safe(exc),
            })
        steps.append({
            "stage": "routes",
            "title": "路線規劃",
            "items": route_items,
            "extra": {"no_feasible_route": route_plan.no_feasible_route},
        })

    # --- 恢復時間 ---
    if ete is not None:
        steps.append({
            "stage": "ete",
            "title": "恢復時間",
            "items": [],
            "extra": {
                "minutes": ete.minutes,
                "formula": ete.formula,
                "recovery_at": ete.recovery_at,
                "base_clearance": ete.base_clearance,
                "average_saturation": ete.average_saturation,
            },
        })

    return steps


def _reason_code_to_text_safe(candidate) -> str:
    """借用 `reporting._reason_code_to_text()`，把排除理由轉成人話。

    刻意重用而不是另寫一份：排除理由的文字在建議書與推理鏈上必須一字不差，
    否則同一條路段在兩個地方會有兩種說法。
    """
    from src.reporting import _reason_code_to_text

    return _reason_code_to_text(candidate.reason_code, candidate)


def build_expected_actions(
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate | None,
) -> list[str]:
    """依命中條款列出應變動作（填 `W1Response.expected_actions`）。

    對照的是 `data/emergency_traffic_sop.json` 各條款的處置要求，跟
    `reporting._generate_c1_c3_fallback()` 用的是同一組敘述——刻意保持一致，
    避免 What-if 講的處置跟正式建議書講的不一樣。
    """
    clauses = {h.clause_id for h in sensing.rule_hits}
    actions: list[str] = []

    if "SOP-1" in clauses:
        actions.append("啟動號誌調整：替代路線綠燈時間增加 25%")
    if "SOP-2" in clauses and route_plan is not None:
        if route_plan.primary:
            actions.append(f"導引車流至 {route_plan.primary.name}")
        if route_plan.secondary:
            actions.append(f"次要分流至 {route_plan.secondary.name}")
    if "SOP-3" in clauses:
        actions.append("通知北捷啟動過站不停措施，調度接駁專車")
    if "SOP-4" in clauses:
        actions.append("大型活動散場疏導：提前部署人流管制")
    if "SOP-5" in clauses:
        actions.append("派遣人工指揮警力（每路口 2 人），CMS 加註請依現場指揮通行")
    if "SOP-6" in clauses:
        actions.append("發布多語（中／英／日／韓）通報簡訊")
    if ete is not None:
        actions.append(f"持續監控至預計恢復時間 {ete.recovery_at}")

    return actions


SCENARIO_REPORT_HEADER = (
    "> ⚠️ **本文件為假設情境推演，非正式決策輸出。**\n"
    "> 內容依使用者提出的假設條件重算，未寫入決策軌跡，不得作為現場執行依據。\n"
)
"""情境建議書的固定抬頭。

一定要有這段：情境建議書跟正式建議書用的是**同一支 prompt、同一個生成函式**，
產出的格式與語氣完全一樣。少了抬頭，兩份文件並排時沒有任何辨識特徵可以區分，
在指揮中心情境下這是會出人命的混淆。抬頭由 Python 硬寫在最前面，不經過 LLM。
"""


def generate_scenario_report(
    incident: Incident,
    outcome: ScenarioOutcome,
    overrides: dict[str, float | int | str],
    base_decision=None,
) -> dict:
    """方案B：把 What-if 重算結果餵進 C1-C4 生成，產出「假設情境建議書」。

    設計要點是**不新增任何生成邏輯**：`run_scenario()` 已經算出跟正式週期同構的
    `SensingResult`／`RoutePlan`／`EteEstimate`，直接交給 `reporting.generate_report()`
    ——同一支 prompt、同一組事實組裝、同一套降級規則。差別只在輸入資料是覆寫後的
    副本。所以「正式建議書」與「情境建議書」的格式、用詞、引用條款方式必然一致，
    並排比較時讀者只需要看數字差異，不必先分辨兩份文件的體例差在哪。

    Args:
        incident: 事故本體（假設情境不改事故本身，只改周邊數據）
        outcome: `compute_scenario()` 的物件版結果
        overrides: 本次套用的假設條件，寫進抬頭供讀者對照
        base_decision: 正式週期的 `DecisionResult`（可為 None）。有值時一併算出
            「跟正式決策差在哪」，這是這份文件最有價值的部分。

    Returns:
        `{"report_text": str|None, "notification": dict|None, "differences": list[dict]}`
        生成失敗時 `report_text` 為 None（沿用 `generate_report()` 的降級語意，
        永不拋例外）。
    """
    from src.reporting import generate_report

    if outcome.ete is None:
        # incident=None 的情境（使用者沒在看特定事件）走不到建議書——沒有事故就
        # 沒有「交控建議」可言。這不是錯誤，是合理的功能邊界。
        return {
            "report_text": None,
            "notification": None,
            "differences": [],
            "unavailable_reason": "此假設情境沒有對應的事故，無法產生交控建議書",
        }

    try:
        report_text, notification = generate_report(
            incident=incident,
            sensing=outcome.sensing,
            route_plan=outcome.route_plan,
            ete=outcome.ete,
            advisory=None,
            bundle=outcome.bundle,
        )
    except Exception:
        logger.exception("情境建議書生成失敗")
        report_text, notification = None, None

    if report_text is not None:
        assumption_lines = "\n".join(f"> - {k} = {v}" for k, v in sorted(overrides.items()))
        header = SCENARIO_REPORT_HEADER
        if assumption_lines:
            header += "> \n> **本次假設條件：**\n" + assumption_lines + "\n"
        report_text = header + "\n---\n\n" + report_text

    differences: list[dict] = []
    if base_decision is not None:
        differences = diff_from_base(
            _decision_to_comparable(base_decision),
            scenario_to_dict(outcome, overrides, incident),
        )

    return {
        "report_text": report_text,
        "notification": _json_safe(notification),
        "differences": differences,
    }


_CLAUSE_ID_PATTERN = re.compile(r"^(?:SOP-|§)\s*(\d+)$")


def _normalize_clause_id(clause: str) -> str:
    """把條款 ID 統一成 `SOP-N`。

    [2026-08-01] 專案裡同一個條款有兩種寫法：`RuleHit.clause_id` 是 `"SOP-2"`，
    而 `DecisionResult.triggered_by` 是 `"§2"`。差異比對直接拿兩邊做集合運算時，
    永遠會回報「全部條款都變了」——實測 base=["§2"]、scenario=["SOP-1", "SOP-2", …]，
    看起來像是假設情境觸發了六條新條款，其實 SOP-2 兩邊都有。

    這裡只做格式正規化，不改任何一邊的原始資料。
    """
    match = _CLAUSE_ID_PATTERN.match(str(clause).strip())
    if match:
        return f"SOP-{match.group(1)}"
    return str(clause)


def _decision_to_comparable(decision) -> dict:
    """把正式週期的 `DecisionResult` 轉成 `diff_from_base()` 吃的形狀。

    `diff_from_base` 的參數形狀是 `run_scenario()` 的回傳值（`rule_hits`/`route_plan`/
    `ete`），而 `DecisionResult` 用的是 `routes`/`ete`、且沒有帶 `rule_hits`
    （條款命中在 `triggered_by`）。這裡做欄位對映，不重算任何東西。
    """
    rule_hits = []
    for clause in getattr(decision, "triggered_by", []) or []:
        # triggered_by 只有條款 ID，沒有 evidence。diff_from_base 的條款集合比對
        # 只讀 clause_id，所以填一個最小結構就夠；traffic_level 另外從
        # decision.level 取（比從 evidence 反推可靠）。
        rule_hits.append({"clause_id": _normalize_clause_id(clause), "evidence": {}})

    return {
        "rule_hits": rule_hits,
        "route_plan": getattr(decision, "routes", None),
        "ete": getattr(decision, "ete", None),
        "_level": getattr(decision, "level", None),
    }


def diff_from_base(base: dict | None, scenario: dict) -> list[dict]:
    """比較 base 與 scenario 的差異，固定四項比對：

    1. traffic_level（從 rule_hits 中取 SOP-1 最高級別）
    2. ete.minutes
    3. route_plan.primary.segment_id / route_plan.secondary.segment_id
    4. 觸發的 SOP clause_id 集合的差集

    base 為 None 時回傳空 list（沒有基準可比）。
    """
    if base is None:
        return []

    diffs: list[dict] = []

    # 輔助：從 rule_hits 提取 traffic_level
    def _extract_level(data: dict) -> str:
        # `_decision_to_comparable()` 直接帶了 DecisionResult.level 進來，比從
        # evidence 反推可靠（正式週期的 level 是 rules.py 算好的權威值），優先採用。
        explicit = data.get("_level")
        if explicit is not None:
            return str(getattr(explicit, "value", explicit))

        hits = data.get("rule_hits", [])
        max_level = "normal"
        for h in hits:
            clause = h.clause_id if hasattr(h, "clause_id") else h.get("clause_id", "")
            if clause == "SOP-1":
                evidence = h.evidence if hasattr(h, "evidence") else h.get("evidence", {})
                val = evidence.value if hasattr(evidence, "value") else evidence.get("value", 0)
                if isinstance(val, (int, float)):
                    if val >= 0.95:
                        max_level = "A"
                    elif val >= 0.85 and max_level != "A":
                        max_level = "B"
        return max_level

    # 1. traffic_level
    base_level = _extract_level(base)
    scenario_level = _extract_level(scenario)
    if base_level != scenario_level:
        diffs.append({"field": "traffic_level", "base_value": base_level, "new_value": scenario_level})

    # 2. ete.minutes
    base_ete = base.get("ete")
    scenario_ete = scenario.get("ete")
    base_minutes = (base_ete.minutes if hasattr(base_ete, "minutes") else base_ete.get("minutes") if isinstance(base_ete, dict) else None) if base_ete else None
    scenario_minutes = (scenario_ete.minutes if hasattr(scenario_ete, "minutes") else scenario_ete.get("minutes") if isinstance(scenario_ete, dict) else None) if scenario_ete else None
    if base_minutes != scenario_minutes:
        diffs.append({"field": "ete.minutes", "base_value": base_minutes, "new_value": scenario_minutes})

    # 3. 主次路線 segment_id
    def _extract_route_ids(data: dict) -> tuple[str | None, str | None]:
        rp = data.get("route_plan")
        if rp is None:
            return None, None
        if hasattr(rp, "primary"):
            primary_id = rp.primary.segment_id if rp.primary else None
            secondary_id = rp.secondary.segment_id if rp.secondary else None
        elif isinstance(rp, dict):
            p = rp.get("primary")
            s = rp.get("secondary")
            primary_id = (p.get("segment_id") if isinstance(p, dict) else (p.segment_id if p else None)) if p else None
            secondary_id = (s.get("segment_id") if isinstance(s, dict) else (s.segment_id if s else None)) if s else None
        else:
            primary_id = None
            secondary_id = None
        return primary_id, secondary_id

    base_primary, base_secondary = _extract_route_ids(base)
    scen_primary, scen_secondary = _extract_route_ids(scenario)
    if base_primary != scen_primary or base_secondary != scen_secondary:
        diffs.append({
            "field": "routes",
            "base_value": {"primary": base_primary, "secondary": base_secondary},
            "new_value": {"primary": scen_primary, "secondary": scen_secondary},
        })

    # 4. 觸發的 SOP clause_id 集合
    def _extract_clause_ids(data: dict) -> set[str]:
        hits = data.get("rule_hits", [])
        result = set()
        for h in hits:
            cid = h.clause_id if hasattr(h, "clause_id") else h.get("clause_id", "")
            if cid:
                result.add(cid)
        return result

    base_clauses = _extract_clause_ids(base)
    scenario_clauses = _extract_clause_ids(scenario)
    if base_clauses != scenario_clauses:
        diffs.append({
            "field": "triggered_sop_clauses",
            "base_value": sorted(base_clauses),
            "new_value": sorted(scenario_clauses),
        })

    return diffs
