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


def _parse_flow_direction(flow_direction: str) -> tuple[str, str | None]:
    """解析 flow_direction 欄位，回傳 (基本方向, 受影響車流方向)。
    
    範例：
    - "東西向" → ("東西向", None)
    - "南北向" → ("南北向", None)
    - "南北向 (事故影響南下車流)" → ("南北向", "南下")
    - "東西向 (事故影響東行車流)" → ("東西向", "東行")
    """
    if "(" in flow_direction:
        base = flow_direction.split("(")[0].strip()
        detail = flow_direction.split("(")[1].replace(")", "").strip()
        # 提取方向關鍵字
        if "南下" in detail:
            affected_flow = "南下"
        elif "北上" in detail:
            affected_flow = "北上"
        elif "東行" in detail:
            affected_flow = "東行"
        elif "西行" in detail:
            affected_flow = "西行"
        else:
            affected_flow = None
        return base, affected_flow
    return flow_direction, None


def _determine_position(
    candidate_name: str,
    affected_segment_intersections: list[str],
    flow_direction: str | None = None,
) -> str:
    """依據 intersections 順序與車流方向判定候選是 upstream/downstream/unknown。

    邏輯：
    1. 若候選路段不在 intersections 中 → "unknown"
    2. 若有明確的 flow_direction（如「南下」「北上」）：
       - 南北向道路：intersections[0] 是北端，intersections[-1] 是南端
         - 南下車流：北端=上游，南端=下游
         - 北上車流：南端=上游，北端=下游
       - 東西向道路：intersections[0] 是西端，intersections[-1] 是東端
         - 東行車流：西端=上游，東端=下游
         - 西行車流：東端=上游，西端=下游
    3. 若無明確方向，預設 intersections[0] = 上游（向後相容）
    """
    if candidate_name not in affected_segment_intersections:
        return "unknown"

    idx = affected_segment_intersections.index(candidate_name)
    total = len(affected_segment_intersections)

    if total <= 1:
        return "upstream"

    # 解析車流方向
    base_direction, affected_flow = _parse_flow_direction(flow_direction or "")

    # 計算相對位置（0.0 = 最前端，1.0 = 最後端）
    relative_pos = idx / (total - 1) if total > 1 else 0

    # 判斷是否需要反轉上下游
    # 預設：intersections[0] = 上游
    # 反轉情況：北上、西行（車流從後端往前端走）
    reverse = affected_flow in ("北上", "西行")

    if reverse:
        # 反轉：後端變上游
        if relative_pos > 0.5:
            return "upstream"
        else:
            return "downstream"
    else:
        # 正常：前端是上游
        if relative_pos < 0.5:
            return "upstream"
        else:
            return "downstream"


_POSITION_LABELS = {
    "upstream": "上游",
    "downstream": "下游",
    "parallel": "平行替代",
    "unknown": "位置未判定",
}


def _describe_selection(
    primary: RouteCandidate | None,
    secondary: RouteCandidate | None,
    *,
    all_alternatives_saturated: bool = False,
) -> str:
    """用一句話交代主/次線是怎麼挑出來的。

    [2026-08-02] 這是「為什麼是這條」的答案。以前這個資訊只存在於
    `sort_key` 這個區域函式裡，沒有任何管道離開 `plan_route()`。

    實測缺口：長官問「為什麼建議走市民大道四段」，模型只能列出誰被排除，
    答不出「為什麼不走飽和度更低的仁愛路四段」——正確答案是上游優先
    （SOP-2 §2a(3)），而那句話系統從來沒說出口過。
    """
    if primary is None:
        return "所有候選路段均被排除，無可行替代路線。"

    if all_alternatives_saturated:
        # 這句話跟下面那句的差別不是措辭，是結論相反：一個是「找到了」，
        # 一個是「找不到，只好指派最不糟的」。用同一句描述兩件事，指揮官
        # 會把飽和路線當成暢通路線看待。
        detail = (
            f"周邊候選路段全數飽和（Saturation ≥ 0.85），**已無可替補的路段**。"
            f"依 SOP-2 §2a 例外仍指派飽和度最低者 {primary.name}"
            f"（{primary.saturation_score}）為主線"
        )
        if secondary is not None:
            detail += f"、{secondary.name}（{secondary.saturation_score}）為次線"
        return (
            detail + "，並啟動長綠燈時制。此為權宜指派而非可行替代路線，"
            "請同步評估人工指揮、區域封閉與大眾運輸疏運。"
        )

    rule = (
        "篩選：容量 ≥ 1000 vph、與事故路段直接相鄰、位於事故點上游（SOP-2 §2a）；"
        "排序：上游候選優先，同組內飽和度低者優先，飽和度相同時取容量大者。"
    )
    pos = _POSITION_LABELS.get(primary.position or "unknown", "位置未判定")
    detail = (
        f"主線 {primary.name} 為{pos}候選中飽和度最低者"
        f"（{primary.saturation_score}）。"
    )
    if secondary is not None:
        spos = _POSITION_LABELS.get(secondary.position or "unknown", "位置未判定")
        if primary.position == "upstream" and secondary.position == "downstream":
            detail += (
                f"次線 {secondary.name} 飽和度較低（{secondary.saturation_score}）"
                f"但位於{spos}，依上游優先原則列為次線。"
            )
        else:
            detail += f"次線 {secondary.name}（{spos}，飽和度 {secondary.saturation_score}）。"
    return rule + " " + detail


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

    # 不能走的路段集合：事故本身 + 呼叫端指定的額外封閉（見 RouteRequest）
    closed_segments = {incident.affected_segment}
    if incident.affected_road:
        closed_segments.add(incident.affected_road)
    closed_segments.update(request.extra_closed_segments or [])

    # 取得事故路段的 alternatives
    alternative_ids = affected_seg.alternatives

    # [2026-08-01 合併修正] 「直接相鄰」該不該當硬排除條件——兩種說法都對一半。
    #
    # SOP-2 §2a(2) 明文要求替代路線必須「與事故路段直接相鄰（出現在其
    # intersections 內）」，ACC_001 的黃金值（主 RD_TPE_004／次 RD_TPE_005）
    # 就是這條篩選跑出來的。
    #
    # 但 branch8 發現一個真問題：15 條路段裡有 **10 條**的 alternatives 全部
    # 通不過這個篩選（例如 RD_TPE_003 基隆路一段的 alternatives 是
    # ['RD_TPE_006', ...]，而它的 intersections 是 ['忠孝東路四段','松高路',
    # '信義路五段']——「敦化南路一段」不在裡面）。結果那 10 條路段一出事就
    # 直接回「無可行替代路線」。
    #
    # 他們的修法是整個移除這道篩選。那修好了 10 條，卻弄壞了 ACC_001：
    # 敦化南路一段（飽和度 0.72）不再被排除，就贏過市民大道四段（0.78）
    # 變成主線，跟 SOP 驗收過的黃金值不符。
    #
    # 兩邊兼顧的做法：**優先套用篩選，篩不出東西時才放寬**。
    #   RD_TPE_002 → 篩得到市民大道四段、仁愛路四段 → 黃金值保住
    #   RD_TPE_003 → 篩完是空的 → 放寬用完整 alternatives → 10 條路段有救
    # 放寬時會記一筆 finding，讓指揮官知道這些路線不是直接相鄰的。
    # 這裡的排除條件必須跟下面迴圈**完全一致**（用同一個 closed_segments），
    # 否則會出現「預判有相鄰候選、實際跑完卻一條都不剩」的矛盾。
    _direct_ok = [
        a for a in alternative_ids
        if a in segment_map
        and a not in closed_segments
        and segment_map[a].capacity_vph >= 1000
        and _is_directly_intersecting(segment_map[a].name, affected_seg.intersections)
    ]
    require_direct_intersection = bool(_direct_ok)

    # R3-R5：逐一評估每個 alternative
    all_candidates: list[RouteCandidate] = []
    upstream_eligible: list[RouteCandidate] = []
    downstream_eligible: list[RouteCandidate] = []
    excluded: list[RouteCandidate] = []
    findings: list[RouteFinding] = []

    if not require_direct_intersection and alternative_ids:
        # 放寬了才記——指揮官要知道這些路線是路網設計者列的替代方案，
        # 但不是 SOP-2 §2a(2) 定義的「直接相鄰」路段。
        findings.append(RouteFinding(
            finding_code="INTERSECTION_FILTER_RELAXED",
            segment_ids=list(alternative_ids),
            evidence={
                "reason": "此路段的 alternatives 均未列於其 intersections，"
                          "套用直接相鄰篩選會得到零候選",
                "affected_segment": affected_seg.segment_id,
                "intersections": list(affected_seg.intersections or []),
                "sop_ref": "SOP-2 §2a(2)",
            },
        ))

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
        #
        # [2026-08-02] `closed_segments` 除了事故本身，還包含呼叫端傳入的
        # `extra_closed_segments`（疊加情境：另一起事件、或使用者假設的第二條
        # 封閉路段）。少了這一段，系統會把一條剛被假設封閉的路推薦成替代路線。
        if alt_id in closed_segments:
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
        # [2026-08-01 修正] 原本檢查候選路段的 name 是否在事故路段的 intersections 裡，
        # 但 intersections 記錄的是「交叉路口名稱」（如「忠孝東路四段」），不是「替代路段名稱」。
        # 例如：RD_TPE_003（基隆路一段）的 alternatives 包含 RD_TPE_006（敦化南路一段），
        # 但 RD_TPE_003 的 intersections 是 ['忠孝東路四段', '松高路', '信義路五段']，
        # 「敦化南路一段」不在裡面，導致所有替代路線都被錯誤排除。
        #
        # 正確邏輯：alternatives 清單本身就是路網設計者預先驗證過的合理替代路線，
        # 不需要再用 intersections 做二次驗證。移除此檢查，改為記錄「是否直接相交」
        # 作為輔助資訊（影響上下游判定），但不作為排除條件。
        #
        # [2026-08-01 合併修正] 上面那段只對了一半——見 `require_direct_intersection`
        # 的完整說明。這道篩選在有直接相鄰候選時仍必須套用（否則 ACC_001 黃金值
        # 會壞掉），只有在篩完會是空的時候才放寬。
        is_directly_intersecting = _is_directly_intersecting(seg.name, affected_seg.intersections)

        if require_direct_intersection and not is_directly_intersecting:
            candidate = RouteCandidate(
                segment_id=alt_id, name=seg.name, eligible=False,
                reason_code="NOT_DIRECTLY_INTERSECTING", saturation_score=sat,
                capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
            )
            all_candidates.append(candidate)
            excluded.append(candidate)
            continue

        # R3 step 5: 上下游判定（根據車流方向）
        # [2026-08-01 修正] 現在會讀取 flow_direction 欄位判斷車流方向
        # 若候選路段在 intersections 裡，依位置 + 車流方向判定；否則視為 parallel
        if is_directly_intersecting:
            position = _determine_position(
                seg.name,
                affected_seg.intersections,
                affected_seg.flow_direction,  # 傳入車流方向
            )
        else:
            position = "parallel"  # 平行替代路線，優先級介於 upstream 和 downstream 之間

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
                position=position,
            )
            all_candidates.append(candidate)
            # 暫存，R4 會決定是否保留（parallel 視為 upstream 優先級）
            if position == "downstream":
                downstream_eligible.append(candidate)
            else:  # upstream 或 parallel
                upstream_eligible.append(candidate)
            excluded.append(candidate)
            continue

        # 通過所有篩選
        candidate = RouteCandidate(
            segment_id=alt_id, name=seg.name, eligible=True,
            reason_code=None, saturation_score=sat,
            capacity_vph=seg.capacity_vph, snapshot_at=snapshot_at,
            position=position,
        )
        all_candidates.append(candidate)

        # parallel（平行替代路線）視為與 upstream 同優先級
        if position == "downstream":
            downstream_eligible.append(candidate)
        else:  # upstream 或 parallel
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
    all_alternatives_saturated = False

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
        # 沒有任何未飽和的候選 → 依 SOP-2 §2a 保留飽和候選，不是放棄。
        #
        # 條文原文：「若主替代路段已飽和 (Saturation_Score >= 0.85)，**仍指派
        # 該路線**並啟動『長綠燈時制』，說明可能仍飽和並建議搭乘大眾運輸。」
        #
        # [2026-08-01 修正] 原本這裡寫 `if len(saturated_candidates) == 1`，
        # 只在**唯一**飽和候選時才保留。那個條件不在 SOP 裡，而且會產生一個
        # 邏輯上說不通的結果：
        #
        #     1 條候選飽和 → 指派該路線 + 長綠燈時制
        #     2 條候選飽和 → 什麼都不給，回報「無可行替代路線」
        #
        # 選項變多反而結果變差。實測就是這樣壞的：假設光復南路坍塌，相鄰候選
        # 市民大道四段(0.98) 與 仁愛路四段(0.92) 都飽和 → 兩條 → 直接放棄，
        # 回「周邊路網全數飽和無法承接」。但 SOP 要的是指派仁愛路四段
        # （飽和度較低、容量 4000）並啟動長綠燈時制。
        #
        # 指揮官需要的是「最不糟的那條路 + 配套措施」，不是「沒有辦法」。
        # 事故現場的車流不會因為系統說沒路就消失。
        saturated_upstream = [c for c in upstream_eligible if c.reason_code == "SATURATED"]
        saturated_downstream = [c for c in downstream_eligible if c.reason_code == "SATURATED"]
        saturated_upstream.sort(key=sort_key)
        saturated_downstream.sort(key=sort_key)
        # 上游優先，跟未飽和情境的排序原則一致
        ranked_saturated = saturated_upstream + saturated_downstream

        if ranked_saturated:
            retained_list: list[RouteCandidate] = []
            for cand in ranked_saturated[:2]:  # 主 + 次，多的仍留在 excluded 供追溯
                retained_new = RouteCandidate(
                    segment_id=cand.segment_id,
                    name=cand.name,
                    eligible=True,
                    reason_code=None,
                    saturation_score=cand.saturation_score,
                    capacity_vph=cand.capacity_vph,
                    snapshot_at=cand.snapshot_at,
                    position=cand.position,
                )
                retained_list.append(retained_new)
                excluded = [e for e in excluded if e.segment_id != cand.segment_id]
                all_candidates = [
                    retained_new if c.segment_id == cand.segment_id else c
                    for c in all_candidates
                ]

            primary = retained_list[0]
            if len(retained_list) > 1:
                secondary = retained_list[1]

            # 走到這條分支就代表：**沒有任何未飽和的候選**。指派出去的是最不糟的
            # 那條，不是可以替補的那條。這個事實必須用一個明確的旗標傳下去，
            # 光靠 `no_feasible_route`（primary is None）表達不出來——見
            # `RoutePlan.all_alternatives_saturated` 的說明。
            all_alternatives_saturated = True

            # finding 要列出全部被保留的路段——指揮官必須知道這些路線**本來就滿了**，
            # 指派它們是「沒有更好的選擇」而不是「這條路很順」。
            #
            # [2026-08-02] `saturation_score`（單數）也一併寫入：`reporting.py` 的
            # 保底模板讀的是單數 key，之前印出來是「飽和度 None」。複數 key 保留
            # 給需要逐段對照的呼叫端（前端地圖、M4B 追問）。
            findings.append(RouteFinding(
                finding_code="SATURATED_BUT_RETAINED",
                segment_ids=[c.segment_id for c in retained_list],
                evidence={
                    "saturation_scores": {
                        c.segment_id: c.saturation_score for c in retained_list
                    },
                    "saturation_score": retained_list[0].saturation_score,
                    "no_unsaturated_alternative": True,
                    "action": "啟動長綠燈時制、綠燈延長 25%，並同步建議改用大眾運輸",
                    "sop_ref": "SOP-2 §2a",
                },
            ))

    elapsed = int((time.perf_counter() - start_time) * 1000)

    return RoutePlan(
        selection_rule=_describe_selection(
            primary, secondary, all_alternatives_saturated=all_alternatives_saturated
        ),
        primary=primary,
        secondary=secondary,
        excluded=excluded,
        findings=findings,
        candidates=all_candidates,
        no_feasible_route=(primary is None),
        all_alternatives_saturated=all_alternatives_saturated,
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
