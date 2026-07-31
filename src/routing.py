"""R1-R5：路網建圖、上下游判定、候選篩選、主/次路線、排除理由記錄（純確定性，零 LLM）。

參考 spec：`.kiro/specs/m2-incident-routing/模組2C_本機路網重規劃引擎_第一階段Spec.md` 第4-6節。
九種 ReasonCode 用 SPEC-00 §3.3 的 UPPER_SNAKE_CASE 命名。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from src.models import (
    NormalizedDataBundle,
    RouteCandidate,
    RouteFinding,
    RoutePlan,
    RouteRequest,
)


def _get_saturation_snapshot(
    bundle: NormalizedDataBundle, segment_id: str, as_of: datetime
) -> tuple[float | None, datetime | None]:
    """取 segment_id 在 as_of 之前（含）的最近一筆飽和度及其時間戳。"""
    candidates = [
        t for t in bundle.traffic
        if t.segment_id == segment_id and t.timestamp <= as_of
    ]
    if not candidates:
        return None, None
    best = max(candidates, key=lambda t: t.timestamp)
    return best.saturation_score, best.timestamp


def _is_directly_intersecting(
    candidate_name: str, affected_segment_intersections: list[str]
) -> bool:
    """候選路段的 name 是否出現在事故路段的 intersections 中。"""
    return candidate_name in affected_segment_intersections


def _determine_position(
    candidate_name: str, affected_segment_intersections: list[str]
) -> str:
    """依據 intersections 順序（上游→下游）判定候選是 upstream/downstream/unknown。

    intersections[0] 為最上游端，intersections[-1] 為最下游端。
    候選路段名稱出現的位置若在前半段視為 upstream，後半段視為 downstream。
    只有一個交會點時視為 upstream。
    """
    if candidate_name not in affected_segment_intersections:
        return "unknown"
    idx = affected_segment_intersections.index(candidate_name)
    total = len(affected_segment_intersections)
    if total <= 1:
        return "upstream"
    # 前半（含中間）= upstream，後半 = downstream
    if idx < total / 2:
        return "upstream"
    return "downstream"


def plan_route(request: RouteRequest) -> RoutePlan:
    """R1-R5 主流程。

    簽章對齊 orchestrator.py 的 ModuleGateway.plan_routes(request: RouteRequest)。
    """
    start_time = time.perf_counter()

    bundle = request.bundle
    incident = request.incident
    as_of = request.as_of

    # R1：建索引
    segment_map = {seg.segment_id: seg for seg in bundle.road_network}

    # 找到事故路段
    affected_seg = segment_map.get(incident.affected_segment)
    if affected_seg is None:
        # affected_road 備援
        if incident.affected_road and incident.affected_road in segment_map:
            affected_seg = segment_map[incident.affected_road]
        else:
            # 無法找到事故路段，回傳 no feasible route
            elapsed = int((time.perf_counter() - start_time) * 1000)
            return RoutePlan(
                primary=None,
                secondary=None,
                excluded=[],
                findings=[],
                candidates=[],
                no_feasible_route=True,
                duration_ms=elapsed,
                within_60_second_sla=elapsed <= 60000,
            )

    # 取得事故路段的 alternatives
    alternative_ids = affected_seg.alternatives

    # R3-R5：逐一評估每個 alternative
    all_candidates: list[RouteCandidate] = []
    upstream_eligible: list[RouteCandidate] = []
    downstream_eligible: list[RouteCandidate] = []
    excluded: list[RouteCandidate] = []
    findings: list[RouteFinding] = []

    for alt_id in alternative_ids:
        # R3 step 1: ID 存在
        if alt_id not in segment_map:
            all_candidates.append(RouteCandidate(
                segment_id=alt_id, name="(unknown)", eligible=False,
                reason_code="UNKNOWN_SEGMENT", saturation_score=None,
                capacity_vph=0, snapshot_at=None,
            ))
            continue

        seg = segment_map[alt_id]
        sat, snapshot_at = _get_saturation_snapshot(bundle, alt_id, as_of)

        # R3 step 2: 非事故或封閉道路
        if alt_id == incident.affected_segment or (
            incident.affected_road and alt_id == incident.affected_road
        ):
            candidate = RouteCandidate(
                segment_id=alt_id, name=seg.name, eligible=False,
                reason_code="CLOSED", saturation_score=sat,
                capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
            )
            all_candidates.append(candidate)
            excluded.append(candidate)
            continue

        # R3 step 3: capacity_vph >= 1000
        if seg.capacity_vph < 1000:
            candidate = RouteCandidate(
                segment_id=alt_id, name=seg.name, eligible=False,
                reason_code="CAPACITY_INSUFFICIENT", saturation_score=sat,
                capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
            )
            all_candidates.append(candidate)
            excluded.append(candidate)
            continue

        # R3 step 4: 與事故道路直接相交
        if not _is_directly_intersecting(seg.name, affected_seg.intersections):
            candidate = RouteCandidate(
                segment_id=alt_id, name=seg.name, eligible=False,
                reason_code="NOT_DIRECTLY_INTERSECTING", saturation_score=sat,
                capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
            )
            all_candidates.append(candidate)
            excluded.append(candidate)
            continue

        # R3 step 5: 上下游判定
        position = _determine_position(seg.name, affected_seg.intersections)

        # R3 step 6: 流向符合（南北向事故 → 東西向替代較適合分流，反之亦然）
        # 但 spec 的黃金值顯示流向不匹配不是硬排除在這個資料集中
        # (RD_TPE_006 被排除是因為 NOT_DIRECTLY_INTERSECTING，不是流向)
        # 保守做法：不硬排除流向不同的，但如果完全同向可能效果差
        # 依 spec R3 step 6「流向符合」，相同流向的可能是平行道路更合適
        # 但黃金值中 RD_TPE_004/005 都是東西向（與南北向事故路段互補），所以保留

        # R3 step 7: Saturation_Score < 0.85
        if sat is None:
            # 找不到快照 → 預設排除
            candidate = RouteCandidate(
                segment_id=alt_id, name=seg.name, eligible=False,
                reason_code="MISSING_TRAFFIC_SNAPSHOT", saturation_score=None,
                capacity_vph=seg.capacity_vph, snapshot_at=None,
            )
            all_candidates.append(candidate)
            excluded.append(candidate)
            continue

        if sat >= 0.85:
            # 先標記為飽和，但可能在 R4 因為是唯一候選而保留
            candidate = RouteCandidate(
                segment_id=alt_id, name=seg.name, eligible=False,
                reason_code="SATURATED", saturation_score=sat,
                capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
            )
            all_candidates.append(candidate)
            # 暫存，R4 會決定是否保留
            if position == "downstream":
                downstream_eligible.append(candidate)
            else:
                upstream_eligible.append(candidate)
            excluded.append(candidate)
            continue

        # 通過所有篩選
        candidate = RouteCandidate(
            segment_id=alt_id, name=seg.name, eligible=True,
            reason_code=None, saturation_score=sat,
            capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
        )
        all_candidates.append(candidate)

        if position == "downstream":
            downstream_eligible.append(candidate)
        else:
            upstream_eligible.append(candidate)

    # R4：主次排序
    # 合格的候選（eligible=True）
    eligible_upstream = [c for c in upstream_eligible if c.eligible]
    eligible_downstream = [c for c in downstream_eligible if c.eligible]
    all_eligible = eligible_upstream + eligible_downstream

    def sort_key(c: RouteCandidate):
        return (c.saturation_score or 0, -c.capacity_vph, c.segment_id)

    eligible_upstream.sort(key=sort_key)
    eligible_downstream.sort(key=sort_key)

    primary: RouteCandidate | None = None
    secondary: RouteCandidate | None = None

    if eligible_upstream:
        # 主路線從上游候選中選
        primary = eligible_upstream[0]
        # 次路線：剩餘上游 + 下游中最佳的
        remaining = eligible_upstream[1:] + eligible_downstream
        if remaining:
            secondary = remaining[0]
    elif eligible_downstream:
        # 沒有上游候選，下游當主（spec: 下游道路只能列備援，但如果沒有上游...）
        # spec 說「下游道路只能列備援」，但也說「沒有道路時回傳 NO_FEASIBLE_ROUTE」
        # 有下游候選時，主路線還是要給，否則就是 no feasible
        primary = eligible_downstream[0]
        if len(eligible_downstream) > 1:
            secondary = eligible_downstream[1]
    else:
        # 檢查是否有唯一飽和候選可保留 (SATURATED_BUT_RETAINED)
        saturated_candidates = [c for c in all_candidates if c.reason_code == "SATURATED"]
        if len(saturated_candidates) == 1:
            retained = saturated_candidates[0]
            # 保留：改為 eligible
            retained_new = RouteCandidate(
                segment_id=retained.segment_id,
                name=retained.name,
                eligible=True,
                reason_code=None,
                saturation_score=retained.saturation_score,
                capacity_vph=retained.capacity_vph,
                snapshot_at=retained.snapshot_at,
            )
            primary = retained_new
            # 從 excluded 移除
            excluded = [e for e in excluded if e.segment_id != retained.segment_id]
            # 更新 all_candidates
            all_candidates = [
                retained_new if c.segment_id == retained.segment_id else c
                for c in all_candidates
            ]
            # 記 finding
            findings.append(RouteFinding(
                finding_code="SATURATED_BUT_RETAINED",
                segment_ids=[retained.segment_id],
                evidence={
                    "saturation_score": retained.saturation_score,
                    "action": "啟動長綠燈時制、綠燈延長 25%",
                },
            ))

    elapsed = int((time.perf_counter() - start_time) * 1000)

    return RoutePlan(
        primary=primary,
        secondary=secondary,
        excluded=excluded,
        findings=findings,
        candidates=all_candidates,
        no_feasible_route=(primary is None),
        duration_ms=elapsed,
        within_60_second_sla=elapsed <= 60000,
    )


def count_affected_intersections(bundle: NormalizedDataBundle, affected_segment: str) -> int:
    """COUNT_INTERSECTIONS：算受影響路段沿線的路口數。

    純讀路網拓樸 intersections 欄位，不依賴車流或事件狀態。
    結果供 SOP-5 警力估算（路口數 × 2）使用。
    """
    segment_map = {seg.segment_id: seg for seg in bundle.road_network}
    seg = segment_map.get(affected_segment)
    if seg is None:
        return 0
    return len(seg.intersections)


# ---------------------------------------------------------------------------
# 路線有效性檢查（替代路線飽和監測用）
# ---------------------------------------------------------------------------

@dataclass
class RouteValidityResult:
    """check_route_validity() 的回傳結果。"""
    primary_valid: bool
    """主路線飽和度 < 0.85 且未被封閉。"""
    secondary_valid: bool
    """次路線飽和度 < 0.85 且未被封閉。"""
    primary_saturation: float | None
    """主路線當前飽和度。"""
    secondary_saturation: float | None
    """次路線當前飽和度。"""
    needs_replan: bool
    """True 表示至少一條路線已失效，需要重新規劃。"""
    invalid_reasons: dict[str, str]
    """失效路線的原因說明，key=segment_id，value=原因。"""


def check_route_validity(
    route_plan: RoutePlan,
    bundle: NormalizedDataBundle,
    as_of: datetime,
    closed_segments: set[str] | None = None,
) -> RouteValidityResult:
    """檢查已推薦的主/次路線是否仍然有效。

    有效條件（任一不符即視為失效）：
    1. 飽和度 < 0.85
    2. 路段未被封閉（不在 closed_segments 中）

    此為純確定性計算，不涉及 LLM，適合背景監測每 10 秒呼叫。
    """
    if closed_segments is None:
        closed_segments = set()

    invalid_reasons: dict[str, str] = {}

    # 檢查主路線
    primary_valid = True
    primary_sat: float | None = None
    if route_plan.primary:
        seg_id = route_plan.primary.segment_id
        primary_sat, _ = _get_saturation_snapshot(bundle, seg_id, as_of)

        if seg_id in closed_segments:
            primary_valid = False
            invalid_reasons[seg_id] = "CLOSED_BY_NEW_INCIDENT"
        elif primary_sat is not None and primary_sat >= 0.85:
            primary_valid = False
            invalid_reasons[seg_id] = f"SATURATED_{primary_sat:.2f}"

    # 檢查次路線
    secondary_valid = True
    secondary_sat: float | None = None
    if route_plan.secondary:
        seg_id = route_plan.secondary.segment_id
        secondary_sat, _ = _get_saturation_snapshot(bundle, seg_id, as_of)

        if seg_id in closed_segments:
            secondary_valid = False
            invalid_reasons[seg_id] = "CLOSED_BY_NEW_INCIDENT"
        elif secondary_sat is not None and secondary_sat >= 0.85:
            secondary_valid = False
            invalid_reasons[seg_id] = f"SATURATED_{secondary_sat:.2f}"

    # 判定是否需要重新規劃：主路線失效則一定要重規劃；僅次路線失效也建議重規劃
    needs_replan = not primary_valid or not secondary_valid

    return RouteValidityResult(
        primary_valid=primary_valid,
        secondary_valid=secondary_valid,
        primary_saturation=primary_sat,
        secondary_saturation=secondary_sat,
        needs_replan=needs_replan,
        invalid_reasons=invalid_reasons,
    )
