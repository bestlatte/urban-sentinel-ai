"""P1-P5：感知計算與 SOP 規則引擎（純確定性，零 LLM）。

參考 spec：`.kiro/specs/m1-data-ingestion/requirements.md` 第五節「P1-P5 函式契約」
（含 SOP-1 城市應變觸發限定路段 vs 全15路段分級的區分，見該文件測試 #6b）；
門檻值權威來源 `.kiro/steering/02-data-contract.md` §4；SOP 原文
`data/emergency_traffic_sop.json`。
"""

from __future__ import annotations

from datetime import datetime

from src.models import (
    CrowdSample,
    EvidenceRef,
    Incident,
    NormalizedDataBundle,
    RuleHit,
    SensingResult,
    TrafficLevel,
    TrafficSample,
)

# SOP-1 城市應變觸發限定這兩條路段（spec §5 P4 門檻值）
_CITY_RESPONSE_SEGMENTS = {"RD_TPE_001", "RD_TPE_002"}


def _as_of_traffic(bundle: NormalizedDataBundle, segment_id: str, as_of: datetime) -> TrafficSample | None:
    """取 segment_id 相符、timestamp <= as_of 的最近一筆。"""
    candidates = [
        t for t in bundle.traffic
        if t.segment_id == segment_id and t.timestamp <= as_of
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t.timestamp)


def _as_of_crowd(bundle: NormalizedDataBundle, station_id: str, as_of: datetime) -> CrowdSample | None:
    """取 station_id 相符、timestamp <= as_of 的最近一筆。"""
    candidates = [
        c for c in bundle.crowd
        if c.station_id == station_id and c.timestamp <= as_of
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.timestamp)


def get_saturation(bundle: NormalizedDataBundle, segment_id: str, as_of: datetime) -> float | None:
    """P1：as-of 飽和度查詢。查無資料回傳 None（不是 0）。"""
    sample = _as_of_traffic(bundle, segment_id, as_of)
    if sample is None:
        return None
    return sample.saturation_score


def get_growth_rate(bundle: NormalizedDataBundle, station_id: str, as_of: datetime) -> float | None:
    """P2：人流成長率查詢（SOP-3/4 用）。"""
    sample = _as_of_crowd(bundle, station_id, as_of)
    if sample is None:
        return None
    return sample.growth_rate


def get_roaming_ratio(bundle: NormalizedDataBundle, station_id: str, as_of: datetime) -> float | None:
    """P3：漫遊比率查詢（SOP-6 用，門檻 >= 0.30）。"""
    sample = _as_of_crowd(bundle, station_id, as_of)
    if sample is None:
        return None
    return sample.roaming_user_pct


def determine_level(rule_hits: list[RuleHit], saturation_score: float | None = None) -> TrafficLevel:
    """P5：交通等級判定。從 rule_hits 中找 SOP-1 命中，回傳最高等級。

    門檻（02-data-contract.md §4，適用全 15 路段）：
        saturation_score >= 0.95 → A
        0.85 <= score < 0.95     → B
        其他                      → normal
    """
    max_level: TrafficLevel = "normal"
    for hit in rule_hits:
        if hit.clause_id == "SOP-1":
            # evidence.value 存的是實際飽和度
            val = hit.evidence.value
            if isinstance(val, (int, float)):
                if val >= 0.95:
                    max_level = "A"
                elif val >= 0.85 and max_level != "A":
                    max_level = "B"
    return max_level


def evaluate_rules(
    bundle: NormalizedDataBundle,
    incident: Incident | None = None,
    as_of: datetime | None = None,
) -> SensingResult:
    """P4：SOP 規則引擎，門檻→條款→動作。彙整 P1-P3 的查詢結果與 P5 的等級判定。

    評估時間優先序：明確傳入的 `as_of` > `incident.timestamp` > bundle 最新時間戳。

    [2026-08-01 新增 `as_of` 參數]
    -----------------------------
    原本只有前兩段，「無 incident 就用資料集最晚時間」這個預設值從來沒有人
    刻意選過，它只是「總得挑一個」的產物。實測發現它會造成很難理解的結果：

        使用者在畫面上看 22:10 的事故，開對話框問「如果市民大道四段封閉…」
        → 前端沒帶 current_trace_id → incident=None
        → as_of 跳到 23:30（資料集最後一筆）
        → 那個時刻 15 條路段有 10 條 ≥0.85
        → 畫面顯示「命中 15 條」

    那 15 條跟使用者的假設**完全無關**，是系統挑了一個跟畫面上差 80 分鐘的
    時間點去掃全市。使用者看到的是一堆無法解釋的命中。

    有了這個參數，呼叫端就能傳「使用者現在正在看的時間」（模擬器時間、
    事故時間），而不是被迫接受一個隱藏的預設值。
    """
    # 決定 as_of 時間
    if as_of is None:
        if incident is not None:
            as_of = incident.timestamp
        else:
            # 取 bundle 中所有時間戳的最大值
            timestamps = [t.timestamp for t in bundle.traffic] + [c.timestamp for c in bundle.crowd]
            as_of = max(timestamps) if timestamps else bundle.loaded_at

    rule_hits: list[RuleHit] = []
    multilingual_required = False

    # --- SOP-1：交通擁塞級別（全 15 路段） ---
    for segment in bundle.road_network:
        sat = get_saturation(bundle, segment.segment_id, as_of)
        if sat is None:
            continue
        if sat >= 0.85:
            hit = RuleHit(
                clause_id="SOP-1",
                segment_id=segment.segment_id,
                evidence=EvidenceRef(
                    field="saturation_score",
                    value=sat,
                    threshold=0.95 if sat >= 0.95 else 0.85,
                ),
                is_primary=False,
                city_response=segment.segment_id in _CITY_RESPONSE_SEGMENTS,
            )
            rule_hits.append(hit)

    # --- SOP-2：車禍路障（需要 incident） ---
    if incident is not None:
        if (
            incident.status in ("Closed", "Blocked", "Restricted")
            and incident.severity.value in ("High", "Critical")
            and incident.affected_segment.startswith("RD_")
        ):
            rule_hits.append(RuleHit(
                clause_id="SOP-2",
                segment_id=incident.affected_segment,
                evidence=EvidenceRef(
                    field="status+severity",
                    value=f"{incident.status}/{incident.severity.value}",
                    threshold="Closed|Blocked|Restricted + High|Critical",
                ),
                is_primary=True,
            ))

    # --- SOP-3：捷運與接駁分流（BS_MRT_BL17） ---
    bl17_sample = _as_of_crowd(bundle, "BS_MRT_BL17", as_of)
    if bl17_sample is not None:
        if bl17_sample.growth_rate > 0.30 or bl17_sample.user_count > 25000:
            rule_hits.append(RuleHit(
                clause_id="SOP-3",
                station_id="BS_MRT_BL17",
                evidence=EvidenceRef(
                    field="growth_rate" if bl17_sample.growth_rate > 0.30 else "user_count",
                    value=bl17_sample.growth_rate if bl17_sample.growth_rate > 0.30 else bl17_sample.user_count,
                    threshold=0.30 if bl17_sample.growth_rate > 0.30 else 25000,
                ),
            ))

    # --- SOP-4：大巨蛋散場（BS_TPE_DOME） ---
    dome_sample = _as_of_crowd(bundle, "BS_TPE_DOME", as_of)
    if dome_sample is not None:
        # 歷史峰值：僅計入 timestamp <= as_of 的記錄
        dome_history = [
            c for c in bundle.crowd
            if c.station_id == "BS_TPE_DOME" and c.timestamp <= as_of
        ]
        peak_count = max((c.user_count for c in dome_history), default=0)
        if peak_count >= 30000 and dome_sample.growth_rate <= -0.20:
            rule_hits.append(RuleHit(
                clause_id="SOP-4",
                station_id="BS_TPE_DOME",
                evidence=EvidenceRef(
                    field="peak_user_count+growth_rate",
                    value=f"peak={peak_count},growth={dome_sample.growth_rate}",
                    threshold="peak>=30000 and growth<=-0.20",
                ),
            ))
            # SOP-4 觸發時同時追加 SOP-3 連動
            sop3_already = any(h.clause_id == "SOP-3" for h in rule_hits)
            if not sop3_already:
                rule_hits.append(RuleHit(
                    clause_id="SOP-3",
                    station_id="BS_TPE_DOME",
                    evidence=EvidenceRef(
                        field="SOP-4_cascade",
                        value=f"peak={peak_count},growth={dome_sample.growth_rate}",
                        threshold="SOP-4 連動觸發",
                    ),
                ))

    # --- SOP-5：號誌故障（需要 incident） ---
    if incident is not None:
        if incident.type == "Power_Failure":
            rule_hits.append(RuleHit(
                clause_id="SOP-5",
                segment_id=incident.affected_segment,
                evidence=EvidenceRef(
                    field="incident_type",
                    value=incident.type,
                    threshold="Power_Failure",
                ),
            ))

    # --- SOP-6：數位通報與多語化（任一站點 roaming_user_pct >= 0.30） ---
    all_station_ids = {c.station_id for c in bundle.crowd}
    for station_id in all_station_ids:
        ratio = get_roaming_ratio(bundle, station_id, as_of)
        if ratio is not None and ratio >= 0.30:
            multilingual_required = True
            rule_hits.append(RuleHit(
                clause_id="SOP-6",
                station_id=station_id,
                evidence=EvidenceRef(
                    field="roaming_user_pct",
                    value=ratio,
                    threshold=0.30,
                ),
            ))

    # --- SOP-7：ETE 公式（不在 P4 命中判定中，只是標示 ETE 需要計算） ---
    # SOP-7 本身不是一個獨立的「命中/不命中」規則，它是一個公式定義，
    # 在有任何事件時由 reporting.py 的 calculate_ete 使用。
    # 但如果有事件存在，標記 SOP-7 命中讓下游知道需要計算 ETE。
    if incident is not None:
        rule_hits.append(RuleHit(
            clause_id="SOP-7",
            segment_id=incident.affected_segment,
            evidence=EvidenceRef(
                field="incident_exists",
                value=incident.event_id,
                threshold="any_incident",
            ),
        ))

    # P5：等級判定
    traffic_level = determine_level(rule_hits)

    return SensingResult(
        traffic_level=traffic_level,
        rule_hits=rule_hits,
        as_of=as_of,
        multilingual_required=multilingual_required,
    )
