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

from src.models import Incident, NormalizedDataBundle, RouteRequest, ScenarioOverrides


def apply_scenario_overrides(
    bundle: NormalizedDataBundle, overrides: dict[str, float | int | str]
) -> NormalizedDataBundle:
    """深拷貝 bundle，依 overrides（key格式 "{entity}.{field}"）覆寫對應欄位。

    entity 前綴 BS_ → 覆寫 CrowdSample（找 station_id 匹配的全部紀錄）
    entity 前綴 RD_ → 覆寫 TrafficSample（找 segment_id 匹配的全部紀錄）
                      或 RoadSegment（如果欄位屬於 RoadSegment）

    找不到對應 entity 時拋 ValueError。
    """
    new_bundle = copy.deepcopy(bundle)

    # 欄位名映射（原始名→正規化名）
    _CROWD_FIELD_MAP = {
        "User_Count": "user_count",
        "user_count": "user_count",
        "Growth_Rate": "growth_rate",
        "growth_rate": "growth_rate",
        "Roaming_User_Pct": "roaming_user_pct",
        "roaming_user_pct": "roaming_user_pct",
        "Stay_Time_Avg": "stay_time_avg",
        "stay_time_avg": "stay_time_avg",
    }
    _TRAFFIC_FIELD_MAP = {
        "Saturation_Score": "saturation_score",
        "saturation_score": "saturation_score",
        "Avg_Speed": "avg_speed",
        "avg_speed": "avg_speed",
        "Vehicle_Count": "vehicle_count",
        "vehicle_count": "vehicle_count",
        "Lane_Status": "lane_status",
        "lane_status": "lane_status",
        "status": "lane_status",  # "status" 映射到 lane_status（最接近的語意）
    }
    _ROAD_FIELD_MAP = {
        "capacity_vph": "capacity_vph",
        "flow_direction": "flow_direction",
    }

    for key, value in overrides.items():
        parts = key.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"override key 格式不合法（需 entity.field）: {key}")
        entity, field = parts

        if entity.startswith("BS_"):
            # 覆寫 CrowdSample
            normalized_field = _CROWD_FIELD_MAP.get(field)
            if normalized_field is None:
                raise ValueError(f"CrowdSample 不支援的欄位: {field}")
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
                    raise ValueError(f"RD_ entity 不支援的欄位: {field}")
        else:
            raise ValueError(f"不支援的 entity 前綴（需 BS_ 或 RD_）: {entity}")

    return new_bundle


def run_scenario(
    bundle: NormalizedDataBundle,
    incident: Incident | None,
    overrides: dict[str, float | int | str],
    gateway,  # ModuleGateway，型別放在 src.orchestrator，這裡不直接 import 避免循環依賴
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
    """
    overridden = apply_scenario_overrides(bundle, overrides)
    sensing = gateway.evaluate_rules(overridden, incident)

    route_plan = None
    ete = None
    if incident is not None:
        route_plan = gateway.plan_routes(
            RouteRequest(incident=incident, bundle=overridden, as_of=incident.timestamp)
        )
        ete = gateway.calculate_ete(incident, overridden)

    return {
        "rule_hits": sensing.rule_hits,
        "route_plan": route_plan,
        "ete": ete,
        "judgment_basis": None,  # TODO(Kiro): 依觸發的 RuleHit.evidence 組出人話敘述
        "current_data_snapshot": None,  # TODO(Kiro): 覆寫後的關鍵欄位快照，供 W1 引用時效性數據
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
