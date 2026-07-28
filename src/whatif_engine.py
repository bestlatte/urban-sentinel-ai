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

    entity 可能是 BS_* 站點（覆寫 CrowdSample）或 RD_* 路段（覆寫 TrafficSample/
    RoadSegment 狀態）；field 是要覆寫的屬性名（如 User_Count/Growth_Rate/status）。

    TODO(Kiro): 依 entity 前綴（BS_/RD_）決定要改 bundle.crowd 還是
    bundle.traffic/road_network 裡對應 id 的紀錄；找不到對應 entity 時應拋
    ValueError（覆寫一個不存在的東西是使用者輸入錯誤，不是靜默忽略）。
    """
    new_bundle = copy.deepcopy(bundle)
    raise NotImplementedError("見本函式 docstring；欄位對照表見 02-data-contract.md §2/3")


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


def diff_from_base(base: dict, scenario: dict) -> list[dict]:
    """[2026-07-28總架構師補充：回應Kiro審查，定案 WhatIfResult.differences_from_base
    的計算方式] `base` 與 `scenario` 都是 `run_scenario()` 的回傳格式（或等價的
    DecisionResult 摘要）。比較粒度固定為以下四項，不逐欄位全比對（太細會讓
    differences 充滿雜訊，例如 duration_ms 一定不同但沒有展示價值）：

        1. traffic_level（"A"/"B"/"normal"，從 rule_hits 或另外傳入）
        2. ete.minutes
        3. route_plan.primary.segment_id / route_plan.secondary.segment_id
        4. 觸發的 SOP clause_id 集合（{h.clause_id for h in rule_hits} 的差集）

    只有值真的不同才放進回傳的 list，每項格式 {"field": str, "base_value": Any,
    "new_value": Any}。base 若為 None（`base_decision_id` 未提供、且找不到
    `base_as_of` 現況可比較），回傳空 list，不是報錯——沒有基準可比時，
    "沒有差異" 是合理預設值，不是錯誤狀態。

    TODO(Kiro): 依上述四項實作比對邏輯。
    """
    raise NotImplementedError("見本函式 docstring")
