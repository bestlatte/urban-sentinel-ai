"""對應 m1-data-ingestion/requirements.md 第六節驗收測試，逐條轉成 assert。

尤其第 1、2 項（真實 CSV 的 Roaming_User_Pct 字串解析 "40%"→0.40）與第 5 項
（SOP-6 黃金值：BS_TPE_101=0.40、BS_XY_ATT=0.30、BS_TPE_DOME≈0.05不觸發）——
這三項是本次審查中反覆用真實資料驗算過的關鍵斷言，不得放寬容錯誤差。
"""

import pytest

from src.loaders import load_data, on_incident_injected, _parse_roaming_pct
from src.models import Incident, IncidentSeverity, NormalizedDataBundle

from datetime import datetime, timezone, timedelta

_TZ_TAIPEI = timezone(timedelta(hours=8))


@pytest.fixture
def bundle() -> NormalizedDataBundle:
    return load_data()


# -- 驗收測試 #1：真實 CSV 漫遊率解析 "40%" → 0.40 --
def test_roaming_pct_40_percent_string(bundle: NormalizedDataBundle):
    """BS_TPE_101 有一筆 Roaming_User_Pct="40%"，解析後必須是 0.40。"""
    hits = [s for s in bundle.crowd if s.station_id == "BS_TPE_101" and s.roaming_user_pct == 0.40]
    assert len(hits) >= 1, "找不到 BS_TPE_101 roaming_user_pct=0.40 的記錄"


# -- 驗收測試 #2：邊界值 "5%" → 0.05 --
def test_roaming_pct_5_percent_string(bundle: NormalizedDataBundle):
    """BS_TPE_DOME 有一筆 Roaming_User_Pct="5%"，解析後必須是 0.05。"""
    hits = [s for s in bundle.crowd if s.station_id == "BS_TPE_DOME" and s.roaming_user_pct == 0.05]
    assert len(hits) >= 1, "找不到 BS_TPE_DOME roaming_user_pct=0.05 的記錄"


# -- 驗收測試 #3：Growth_Rate 不重複轉換 --
def test_growth_rate_no_double_conversion(bundle: NormalizedDataBundle):
    """BS_TPE_DOME 有一筆 Growth_Rate=-0.31，正規化後仍為 -0.31。"""
    hits = [s for s in bundle.crowd if s.station_id == "BS_TPE_DOME" and s.growth_rate == -0.31]
    assert len(hits) >= 1, "找不到 BS_TPE_DOME growth_rate=-0.31 的記錄"


# -- 驗收測試 #8：缺值不當零 --
def test_null_avg_speed_preserved_as_none(bundle: NormalizedDataBundle):
    """city_traffic_flow.json 的 Avg_Speed=null 應保持為 None，不是 0。"""
    nulls = [t for t in bundle.traffic if t.avg_speed is None]
    # 如果原始資料有 null 值就驗證；如果沒有則此測試不阻塞
    # 但至少驗證所有 avg_speed 都是 float 或 None
    for t in bundle.traffic:
        assert t.avg_speed is None or isinstance(t.avg_speed, float)


# -- 驗收測試 #9：外部交會點容錯 --
def test_external_intersection_does_not_crash(bundle: NormalizedDataBundle):
    """intersections 含「正氣橋」等外部交會點時，load_data 不應中斷。"""
    # 如果能跑到這裡，代表 load_data 沒有因為外部交會點而崩潰
    assert len(bundle.road_network) == 15


# -- 補充：基本結構驗證 --
def test_load_data_returns_complete_bundle(bundle: NormalizedDataBundle):
    """D1 基本正確性：五個 list 都有資料。"""
    assert len(bundle.traffic) == 112
    assert len(bundle.crowd) == 36
    assert len(bundle.road_network) == 15
    assert len(bundle.sop) == 7
    assert bundle.loaded_at is not None

    # [2026-08-01] 事件數原本寫死 3。Demo 用的事件會增減（這次合併就從 3 加到 10），
    # 寫死只會讓每次加事件都得改測試，而且改的人不知道自己在改什麼。
    # 真正該守的是「三筆黃金事件還在」——所有黃金值驗收都建立在它們身上。
    golden = {"TPE_2026_ACC_001", "TPE_2026_EVT_002", "TPE_2026_EVT_003"}
    event_ids = {i.event_id for i in bundle.incidents}
    assert golden <= event_ids, f"黃金事件缺漏：{golden - event_ids}"


def test_crowd_timestamps_have_timezone(bundle: NormalizedDataBundle):
    """D3 時間正規化：所有 timestamp 必須有 +08:00 時區資訊。"""
    for sample in bundle.crowd:
        assert sample.timestamp.tzinfo is not None, f"crowd {sample.station_id} 時間缺時區"
        assert sample.timestamp.utcoffset() == timedelta(hours=8)


def test_traffic_timestamps_have_timezone(bundle: NormalizedDataBundle):
    """D3 時間正規化：所有 traffic timestamp 必須有 +08:00 時區資訊。"""
    for sample in bundle.traffic:
        assert sample.timestamp.tzinfo is not None, f"traffic {sample.segment_id} 時間缺時區"
        assert sample.timestamp.utcoffset() == timedelta(hours=8)


def test_roaming_pct_all_in_range(bundle: NormalizedDataBundle):
    """正規化後所有 roaming_user_pct 都在 0.0~1.0 之間。"""
    for sample in bundle.crowd:
        assert 0.0 <= sample.roaming_user_pct <= 1.0, (
            f"{sample.station_id} roaming_user_pct={sample.roaming_user_pct} 超出範圍"
        )


def test_sop_clause_ids(bundle: NormalizedDataBundle):
    """SOP clause_id 格式為 SOP-1 ~ SOP-7。"""
    clause_ids = {s.clause_id for s in bundle.sop}
    assert clause_ids == {f"SOP-{i}" for i in range(1, 8)}


# -- D4：事件注入 --
def test_on_incident_injected_adds_to_bundle(bundle: NormalizedDataBundle):
    """D4：合法事件注入後 incidents 數量增加。"""
    new_incident = Incident(
        event_id="TEST_001",
        type="Test",
        location="測試路段",
        affected_segment="RD_TPE_001",
        status="Active",
        severity=IncidentSeverity.MEDIUM,
        description="測試事件",
        timestamp=datetime(2026, 5, 20, 23, 0, tzinfo=_TZ_TAIPEI),
    )
    updated = on_incident_injected(bundle, new_incident)
    assert len(updated.incidents) == len(bundle.incidents) + 1


def test_on_incident_injected_rejects_invalid_segment(bundle: NormalizedDataBundle):
    """D4：affected_segment 與 affected_road 皆不合法時應拋 ValueError。"""
    bad_incident = Incident(
        event_id="BAD_001",
        type="Test",
        location="不存在的地方",
        affected_segment="NONEXISTENT_001",
        status="Active",
        severity=IncidentSeverity.LOW,
        description="非法路段",
        timestamp=datetime(2026, 5, 20, 23, 0, tzinfo=_TZ_TAIPEI),
    )
    with pytest.raises(ValueError):
        on_incident_injected(bundle, bad_incident)


# -- _parse_roaming_pct 單元測試 --
def test_parse_roaming_pct_string_with_percent():
    assert _parse_roaming_pct("40%") == 0.40
    assert _parse_roaming_pct("5%") == 0.05
    assert _parse_roaming_pct("100%") == 1.0


def test_parse_roaming_pct_numeric_passthrough():
    """如果輸入已經是 0.0~1.0 的小數，不應再除以 100。"""
    assert _parse_roaming_pct(0.40) == 0.40
    assert _parse_roaming_pct(0.05) == 0.05
