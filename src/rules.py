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


def determine_level(rule_hits: list[RuleHit]) -> TrafficLevel:
    """P5：交通等級判定。從 rule_hits 中找 SOP-1 命中，回傳最高等級。

    [2026-08-02] 移除沒有作用的 `saturation_score` 參數。它從來沒有被讀取過，
    全 repo 也沒有任何呼叫端傳過它——留著只會讓人以為「傳一個飽和度進去可以
    影響判定」，實際上傳了完全沒事發生。真的要算單一路段請用
    `determine_level_for_segment()`。

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


def determine_level_for_segment(
    bundle: NormalizedDataBundle,
    segment_id: str,
    as_of: datetime,
) -> TrafficLevel:
    """針對單一路段計算交通等級（事件注入時使用）。
    
    與 determine_level() 不同：這個函式只看指定路段的飽和度，
    不是取全市最高值。用於事件注入時，讓 DecisionResult.level
    反映該事件影響路段的實際狀況。
    """
    sat = get_saturation(bundle, segment_id, as_of)
    if sat is None:
        return "normal"
    if sat >= 0.95:
        return "A"
    if sat >= 0.85:
        return "B"
    return "normal"


# ---------------------------------------------------------------------------
# EvidenceRef 的人話化（唯一來源）
#
# [2026-08-02] `EvidenceRef` 的 field/value/threshold 是**給程式比對用的**，
# 三個欄位加起來就是一條規則的判定依據。前端原本直接把它們串起來顯示，
# 於是「適用條款」面板長成這樣：
#
#     SOP-2  光復南路
#     status+severity Closed/Critical 門檻 Closed|Blocked|Restricted + High|Critical
#
# 數值型的（飽和度 0.9 門檻 0.85）這樣看還可以，但列舉與組合條件就變成
# 內部代碼直接漏到指揮官面前。判定邏輯寫在本檔，措辭就該跟著寫在本檔——
# 放前端會漂移（門檻改了、文案沒改），放 whatif_engine 則只有對話用得到。
# ---------------------------------------------------------------------------

_FIELD_LABELS: dict[str, str] = {
    "saturation_score": "飽和度",
    "status+severity": "路段狀態與嚴重度",
    "growth_rate": "人流成長率",
    "user_count": "站點人數",
    "peak_user_count+growth_rate": "散場人流判定",
    "SOP-4_cascade": "SOP-4 連動觸發",
    "incident_type": "事件類型",
    "roaming_user_pct": "境外漫遊比率",
    "incident_exists": "進行中事件",
}

_STATUS_LABELS: dict[str, str] = {
    "Closed": "全線封閉",
    "Blocked": "阻斷",
    "Restricted": "車道管制",
    "Caution": "注意",
    "Open": "正常通行",
    "Partial_Open": "部分開放",
    "Resolved": "已解除",
}

_SEVERITY_LABELS: dict[str, str] = {
    "Critical": "極嚴重",
    "High": "高",
    "Medium": "中",
    "Low": "低",
}

_INCIDENT_TYPE_LABELS: dict[str, str] = {
    "Road_Collapse_Accident": "路面塌陷",
    "Traffic_Accident": "交通事故",
    "Vehicle_Fire": "車輛火警",
    "Crowd_Surge_Injury": "人群推擠傷亡",
    "Large_Event_Dispersal": "大型活動散場",
    "Power_Failure": "號誌／電力故障",
    "Water_Main_Break": "水管破裂",
    "Debris_On_Road": "路面掉落物",
}


def _pct(value) -> str:
    """0.30 → 「30%」。人流成長率與漫遊比率用百分比比小數好讀。"""
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(value)


def describe_evidence(field: str, value, threshold) -> dict[str, str]:
    """把一條 `EvidenceRef` 轉成三段人話：欄位名、實際值、門檻。

    回傳 `{"field_label", "value_label", "threshold_label"}`，
    呼叫端要湊成什麼句子由呼叫端決定（前端的排版與建議書的敘述不同）。
    無法辨識的 field 一律退回原字串——寧可顯示原始代碼，也不要編一個看起來
    很合理但其實對不上判定邏輯的說法。
    """
    label = _FIELD_LABELS.get(field, field)

    if field == "status+severity":
        # value 形如 "Closed/Critical"；threshold 是三種狀態 × 兩種嚴重度的組合
        status, _, severity = str(value).partition("/")
        value_label = (
            f"{_STATUS_LABELS.get(status, status)}／嚴重度{_SEVERITY_LABELS.get(severity, severity)}"
        )
        return {
            "field_label": label,
            "value_label": value_label,
            "threshold_label": "封閉、阻斷或管制，且嚴重度為高或極嚴重",
        }

    if field == "incident_type":
        return {
            "field_label": label,
            "value_label": _INCIDENT_TYPE_LABELS.get(str(value), str(value)),
            "threshold_label": _INCIDENT_TYPE_LABELS.get(str(threshold), str(threshold)),
        }

    if field == "incident_exists":
        # SOP-7 不是門檻型規則，它只是「有事件就要算 ETE」。
        # 顯示成「incident_exists WHATIF_RD_TPE_002 門檻 any_incident」毫無意義。
        return {
            "field_label": label,
            "value_label": str(value),
            "threshold_label": "有進行中事件即需推算恢復時間",
        }

    if field in ("growth_rate", "roaming_user_pct"):
        return {
            "field_label": label,
            "value_label": _pct(value),
            "threshold_label": _pct(threshold),
        }

    if field == "peak_user_count+growth_rate":
        # value 形如 "peak=31000,growth=-0.25"
        parts = dict(
            p.split("=", 1) for p in str(value).split(",") if "=" in p
        )
        peak = parts.get("peak", "?")
        growth = parts.get("growth", "?")
        return {
            "field_label": label,
            "value_label": f"歷史峰值 {peak} 人、成長率 {_pct(growth)}",
            "threshold_label": "峰值達 30000 人且成長率降至 -20% 以下",
        }

    if field == "SOP-4_cascade":
        return {
            "field_label": label,
            "value_label": "大巨蛋散場已觸發",
            "threshold_label": "SOP-4 命中時自動連動 SOP-3",
        }

    if field == "user_count":
        return {
            "field_label": label,
            "value_label": f"{value} 人",
            "threshold_label": f"{threshold} 人",
        }

    return {
        "field_label": label,
        "value_label": str(value),
        "threshold_label": str(threshold),
    }


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
    #
    # [2026-08-02] 中間插入「模擬器時刻」這一段。原本 incident=None 時直接跳到
    # 資料集最晚時間（23:30），於是**模擬器停在 22:10，Dashboard 的應變等級卻是
    # 23:30 算出來的**——F1 KPI、rules.evaluated.v1 推播、啟動時的全量掃描三處
    # 全都受影響，畫面上的時間與數字對不起來。
    #
    # 資料集最晚時間仍是最後的退路（模擬器沒啟用時），行為不變。
    if as_of is None:
        if incident is not None:
            as_of = incident.timestamp
        else:
            from src import clock

            as_of = clock.simulation_time()
        if as_of is None:
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
