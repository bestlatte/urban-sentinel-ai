"""D1-D4：五個 canonical 檔案載入與 raw→normalized 正規化。

參考 spec：`.kiro/specs/m1-data-ingestion/requirements.md`（完整函式契約、正規化規則、
真實 CSV 的 % 字串解析範例、10 項驗收測試）；資料來源與單位換算規則另見
`.kiro/steering/02-data-contract.md` §1-3。

本模組是唯一可以讀 `data/` 原始檔的地方（01-module-boundaries.md 規則2），
其他模組一律透過 `load_data()` 回傳的 `NormalizedDataBundle` 取用資料。
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.models import (
    CrowdSample,
    Incident,
    IncidentSeverity,
    NormalizedDataBundle,
    RoadSegment,
    SopClause,
    TrafficSample,
)

logger = logging.getLogger(__name__)

_TZ_TAIPEI = timezone(timedelta(hours=8))
_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _parse_timestamp(raw: str) -> datetime:
    """解析多種時間格式，統一輸出 Asia/Taipei (+08:00)。"""
    raw = raw.strip()
    # 嘗試帶秒格式
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=_TZ_TAIPEI)
        except ValueError:
            continue
    # ISO 8601 with timezone
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    raise ValueError(f"無法解析時間格式: {raw}")


def _parse_roaming_pct(raw) -> float:
    """處理兩種格式：帶 % 字串（如 "40%"）或純數字。"""
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.endswith("%"):
            return float(raw[:-1]) / 100.0
        return float(raw) / 100.0 if float(raw) > 1.0 else float(raw)
    # 已經是數字型態
    val = float(raw)
    if val > 1.0:
        return val / 100.0
    return val


def _load_traffic() -> list[TrafficSample]:
    """D1: city_traffic_flow.json"""
    path = _DATA_DIR / "city_traffic_flow.json"
    with open(path, encoding="utf-8") as f:
        raw_list = json.load(f)

    samples = []
    for row in raw_list:
        avg_speed = row.get("Avg_Speed")
        if avg_speed is not None:
            avg_speed = float(avg_speed)

        samples.append(TrafficSample(
            timestamp=_parse_timestamp(row["Timestamp"]),
            segment_id=row["Segment_ID"],
            road_name=row["Road_Name"],
            avg_speed=avg_speed,
            vehicle_count=int(row["Vehicle_Count"]),
            saturation_score=float(row["Saturation_Score"]),
            lane_status=row["Lane_Status"],
        ))
    return samples


def _load_crowd() -> list[CrowdSample]:
    """D1: signaling_crowd_density.csv — 真實資料，Roaming_User_Pct 是帶 % 字串。"""
    path = _DATA_DIR / "signaling_crowd_density.csv"
    samples = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(CrowdSample(
                timestamp=_parse_timestamp(row["Timestamp"]),
                station_id=row["BS_ID"],
                station_name=row["Location_Name"],
                user_count=int(row["User_Count"]),
                stay_time_avg=float(row["Stay_Time_Avg"]),
                growth_rate=float(row["Growth_Rate"]),
                roaming_user_pct=_parse_roaming_pct(row["Roaming_User_Pct"]),
            ))
    return samples


def _load_road_network() -> tuple[list[RoadSegment], list[str]]:
    """D1: road_network_topology.json。回傳 (segments, warnings)。"""
    path = _DATA_DIR / "road_network_topology.json"
    with open(path, encoding="utf-8") as f:
        raw_list = json.load(f)

    segments = []
    warnings: list[str] = []
    all_segment_ids = {r["segment_id"] for r in raw_list}
    all_names = {r["name"] for r in raw_list}

    for row in raw_list:
        # D2 驗證：alternatives 內的 segment_id 必須存在
        for alt in row.get("alternatives", []):
            if alt not in all_segment_ids:
                warnings.append(f"alternatives 引用不存在的 segment_id: {alt} (in {row['segment_id']})")

        # D2 驗證：intersections 內名稱若查無對應，記 warning 不中斷
        for intersection_name in row.get("intersections", []):
            if intersection_name not in all_names:
                warnings.append(f"intersections 含外部交會點: {intersection_name} (in {row['segment_id']})")

        segments.append(RoadSegment(
            segment_id=row["segment_id"],
            name=row["name"],
            flow_direction=row["flow_direction"],
            intersections=row.get("intersections", []),
            capacity_vph=int(row["capacity_vph"]),
            alternatives=row.get("alternatives", []),
            nearby_stations=row.get("nearby_stations", []),
        ))

    return segments, warnings


def _load_incidents() -> list[Incident]:
    """D1: live_incidents.json"""
    path = _DATA_DIR / "live_incidents.json"
    with open(path, encoding="utf-8") as f:
        raw_list = json.load(f)

    incidents = []
    for row in raw_list:
        incidents.append(Incident(
            event_id=row["event_id"],
            type=row["type"],
            location=row["location"],
            affected_segment=row["affected_segment"],
            affected_road=row.get("affected_road"),
            status=row["status"],
            severity=IncidentSeverity(row["severity"]),
            description=row["description"],
            timestamp=_parse_timestamp(row["timestamp"]),
        ))
    return incidents


def _load_sop() -> list[SopClause]:
    """D1: emergency_traffic_sop.json"""
    path = _DATA_DIR / "emergency_traffic_sop.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    return [
        SopClause(
            section_number=s["section_number"],
            title=s["title"],
            content=s["content"],
        )
        for s in raw["sections"]
    ]


_SEEN_DATA_WARNINGS: set[str] = set()
"""已經回報過的資料品質警告，用來去重。

[2026-08-01] `load_data()` 沒有快取，每次呼叫都重讀並重新驗證五個 JSON 檔。
呼叫端包含每 10 秒跑一次的背景規則監測（`main.py::_periodic_rule_monitor`）、
模擬器每個模擬分鐘一次，以及每一個 API 請求。於是這行警告

    intersections 含外部交會點: 正氣橋 (in RD_TPE_009)

**每 10 秒重複一次，永遠不停**，把主控台洗到看不見真正該注意的訊息
（Bedrock 降級、生成失敗都是 WARNING 等級，混在裡面就等於沒有）。

這類警告描述的是**靜態資料檔的性質**——檔案不改就不會變，講一次就夠了。
重複講不會讓它更真，只會讓其他訊息更難被看見。

用行程層級的 set 而不是 `lru_cache`：警告清單是 `_load_road_network()` 的
回傳值，不是 `load_data()` 的參數，快取函式沒有適合的鍵。
"""


def load_data() -> NormalizedDataBundle:
    """載入並正規化五個 canonical 檔案（D1-D3）。

    任一檔案不存在或格式無法解析時拋例外（DATA_NOT_FOUND 語意），
    不得回傳部分資料靜默繼續。
    """
    traffic = _load_traffic()
    crowd = _load_crowd()
    road_network, warnings = _load_road_network()
    incidents = _load_incidents()
    sop = _load_sop()

    # 每種資料品質警告每個行程只講一次（見 `_SEEN_DATA_WARNINGS`）。
    # 刻意不降級成 DEBUG——它仍然是該修的資料問題，只是不需要每 10 秒提醒一次。
    for w in warnings:
        if w not in _SEEN_DATA_WARNINGS:
            _SEEN_DATA_WARNINGS.add(w)
            logger.warning("%s（同類警告本次啟動後不再重複）", w)

    return NormalizedDataBundle(
        traffic=traffic,
        crowd=crowd,
        road_network=road_network,
        incidents=incidents,
        sop=sop,
        loaded_at=datetime.now(tz=_TZ_TAIPEI),
    )


def on_incident_injected(bundle: NormalizedDataBundle, incident: Incident) -> NormalizedDataBundle:
    """D4：事件注入監聽，把新事件併入 bundle（不重新載入整份資料）。

    驗證 affected_segment 或 affected_road 至少一項對應合法 ID，
    驗證失敗拋 ValueError（VALIDATION_ERROR 語意）。
    """
    valid_segment_ids = {seg.segment_id for seg in bundle.road_network}
    valid_station_ids = set()
    for seg in bundle.road_network:
        valid_station_ids.update(seg.nearby_stations)

    has_valid_segment = incident.affected_segment in valid_segment_ids
    has_valid_road = incident.affected_road is not None and incident.affected_road in valid_segment_ids
    has_valid_station = incident.affected_segment in valid_station_ids

    if not (has_valid_segment or has_valid_road or has_valid_station):
        raise ValueError(
            f"affected_segment '{incident.affected_segment}' / affected_road "
            f"'{incident.affected_road}' 無法對應到合法路段或站點 ID"
        )

    updated_incidents = list(bundle.incidents) + [incident]
    return bundle.model_copy(update={"incidents": updated_incidents})
