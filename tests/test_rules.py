"""對應 m1-data-ingestion/requirements.md 第六節，含測試 #6/#6b（SOP-1 全15路段分級
vs 城市應變觸發限定RD_TPE_001/002 兩段的區分——這是本次審查修過的真實bug，
兩條測試都要留著當回歸測試，不能只留一條）。
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.loaders import load_data
from src.models import Incident, IncidentSeverity, NormalizedDataBundle
from src.rules import (
    evaluate_rules,
    get_saturation,
    get_growth_rate,
    get_roaming_ratio,
    determine_level,
)

_TZ_TAIPEI = timezone(timedelta(hours=8))


@pytest.fixture
def bundle() -> NormalizedDataBundle:
    return load_data()


# -- 驗收測試 #4：as-of join 正確性 --
def test_as_of_join_does_not_use_future_data(bundle: NormalizedDataBundle):
    """查詢 BS_TPE_101 在 22:10 的漫遊率，應回傳 20:00 那筆（0.40），不得回傳 22:15。"""
    as_of = datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI)
    ratio = get_roaming_ratio(bundle, "BS_TPE_101", as_of)
    assert ratio == 0.40


# -- 驗收測試 #5：SOP-6 黃金值 --
def test_sop6_golden_values(bundle: NormalizedDataBundle):
    """as-of 22:00：BS_TPE_101(0.40) 和 BS_XY_ATT(0.30) 命中；BS_TPE_DOME 不命中。"""
    as_of = datetime(2026, 5, 20, 22, 0, tzinfo=_TZ_TAIPEI)

    ratio_101 = get_roaming_ratio(bundle, "BS_TPE_101", as_of)
    ratio_att = get_roaming_ratio(bundle, "BS_XY_ATT", as_of)
    ratio_dome = get_roaming_ratio(bundle, "BS_TPE_DOME", as_of)

    assert ratio_101 == 0.40
    assert ratio_att == 0.30
    assert ratio_dome is not None and ratio_dome < 0.30  # ~0.05


def test_sop6_multilingual_triggered(bundle: NormalizedDataBundle):
    """SOP-6 命中時 multilingual_required 必須為 True。"""
    as_of = datetime(2026, 5, 20, 22, 0, tzinfo=_TZ_TAIPEI)
    result = evaluate_rules(bundle, incident=None)
    # 用 22:00 as_of 跑（bundle 最大 timestamp 涵蓋 22:00 之後的資料也行，
    # 但 evaluate_rules 沒有 incident 時取 bundle 最新 timestamp）
    # 直接用 incident 指定 as_of 更精確
    from src.models import Incident, IncidentSeverity
    # 建一個假 incident 只為了鎖定 as_of=22:00
    dummy = Incident(
        event_id="DUMMY", type="Test", location="test",
        affected_segment="RD_TPE_001", status="Active",
        severity=IncidentSeverity.MEDIUM, description="",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=dummy)
    sop6_hits = [h for h in result.rule_hits if h.clause_id == "SOP-6"]
    triggered_stations = {h.station_id for h in sop6_hits}
    assert "BS_TPE_101" in triggered_stations
    assert "BS_XY_ATT" in triggered_stations
    assert "BS_TPE_DOME" not in triggered_stations
    assert result.multilingual_required is True


# -- 驗收測試 #6：SOP-1 黃金值 --
def test_sop1_ab_level_applies_to_all_15_segments(bundle: NormalizedDataBundle):
    """RD_TPE_002 at 22:10 → saturation=1.0 → A級，且帶城市應變觸發段判定。"""
    as_of = datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI)
    sat = get_saturation(bundle, "RD_TPE_002", as_of)
    assert sat == 1.0

    # 建一個 incident 鎖定 as_of
    dummy = Incident(
        event_id="DUMMY", type="Test", location="test",
        affected_segment="RD_TPE_002", status="Active",
        severity=IncidentSeverity.MEDIUM, description="",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=dummy)

    # RD_TPE_002 應有 SOP-1 命中
    sop1_002 = [h for h in result.rule_hits if h.clause_id == "SOP-1" and h.segment_id == "RD_TPE_002"]
    assert len(sop1_002) >= 1
    assert sop1_002[0].evidence.value == 1.0
    assert sop1_002[0].city_response is True

    # 等級必須是 A
    assert result.traffic_level == "A"


# -- 驗收測試 #6b：SOP-1 分級不限定路段 --
def test_sop1_city_response_limited_to_two_segments(bundle: NormalizedDataBundle):
    """RD_TPE_003（非城市應變觸發路段）at 22:00 → sat>=0.95 → 仍正確判為 A 級並產生
    RuleHit，但不帶 CITY_RESPONSE flag。"""
    as_of = datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI)
    sat = get_saturation(bundle, "RD_TPE_003", as_of)
    # RD_TPE_003 at 22:30 sat=1.0
    assert sat is not None and sat >= 0.95

    dummy = Incident(
        event_id="DUMMY", type="Test", location="test",
        affected_segment="RD_TPE_003", status="Active",
        severity=IncidentSeverity.MEDIUM, description="",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=dummy)

    # RD_TPE_003 有 SOP-1 RuleHit
    sop1_003 = [h for h in result.rule_hits if h.clause_id == "SOP-1" and h.segment_id == "RD_TPE_003"]
    assert len(sop1_003) >= 1

    # RD_TPE_003 不是城市應變觸發段，city_response 必須為 False
    assert sop1_003[0].city_response is False

    # 等級仍為 A（分級不因路段而異）
    assert result.traffic_level == "A"


# -- 驗收測試 #7：SOP-4 黃金值 --
def test_sop4_dome_triggers_at_2200(bundle: NormalizedDataBundle):
    """BS_TPE_DOME at 22:00 → 峰值 40000（19:00）、當前 22000、growth -0.31 → 觸發，且追加 SOP-3。"""
    as_of = datetime(2026, 5, 20, 22, 0, tzinfo=_TZ_TAIPEI)
    dummy = Incident(
        event_id="DUMMY", type="Test", location="test",
        affected_segment="RD_TPE_007", status="Active",
        severity=IncidentSeverity.MEDIUM, description="",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=dummy)

    sop4_hits = [h for h in result.rule_hits if h.clause_id == "SOP-4"]
    assert len(sop4_hits) >= 1
    assert sop4_hits[0].station_id == "BS_TPE_DOME"

    # SOP-4 觸發時追加 SOP-3 連動
    sop3_hits = [h for h in result.rule_hits if h.clause_id == "SOP-3"]
    assert len(sop3_hits) >= 1


# -- 驗收測試 #10：相同輸入相同輸出（決定性） --
def test_evaluate_rules_is_deterministic(bundle: NormalizedDataBundle):
    """連續呼叫兩次 evaluate_rules，結果完全一致。"""
    as_of = datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI)
    dummy = Incident(
        event_id="ACC_001", type="Road_Collapse_Accident", location="test",
        affected_segment="RD_TPE_002", status="Closed",
        severity=IncidentSeverity.CRITICAL, description="",
        timestamp=as_of,
    )
    r1 = evaluate_rules(bundle, incident=dummy)
    r2 = evaluate_rules(bundle, incident=dummy)

    assert r1.traffic_level == r2.traffic_level
    assert len(r1.rule_hits) == len(r2.rule_hits)
    assert r1.multilingual_required == r2.multilingual_required


# -- ACC_001 golden event: SOP-2 命中 + SOP-1/6/7 並行 --
def test_acc001_sop_hits(bundle: NormalizedDataBundle):
    """ACC_001：路面塌陷 22:10，主因 SOP-2（並命中 1、6、7）。"""
    as_of = datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI)
    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="光復南路/忠孝東路口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="路面塌陷",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=incident)

    clause_ids = {h.clause_id for h in result.rule_hits}
    assert "SOP-2" in clause_ids, "ACC_001 應命中 SOP-2"
    assert "SOP-1" in clause_ids, "ACC_001 應命中 SOP-1"
    assert "SOP-7" in clause_ids, "ACC_001 應命中 SOP-7"

    # SOP-2 應標為 is_primary
    sop2_hits = [h for h in result.rule_hits if h.clause_id == "SOP-2"]
    assert sop2_hits[0].is_primary is True

    # 等級為 A（RD_TPE_002 sat=1.0）
    assert result.traffic_level == "A"


# -- EVT_002 golden event: SOP-3 命中 --
def test_evt002_sop_hits(bundle: NormalizedDataBundle):
    """EVT_002：人群推擠 22:20，SOP-3 命中（BL17 user_count=31000>25000 at 22:15 as-of）。"""
    as_of = datetime(2026, 5, 20, 22, 20, tzinfo=_TZ_TAIPEI)
    incident = Incident(
        event_id="TPE_2026_EVT_002",
        type="Crowd_Surge_Injury",
        location="捷運國父紀念館站",
        affected_segment="BS_MRT_BL17",
        affected_road="RD_TPE_001",
        status="Active",
        severity=IncidentSeverity.HIGH,
        description="人群推擠",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=incident)

    clause_ids = {h.clause_id for h in result.rule_hits}
    assert "SOP-3" in clause_ids, "EVT_002 應命中 SOP-3（BL17 user_count>25000）"


# -- EVT_003 golden event: SOP-5 命中 --
def test_evt003_sop_hits(bundle: NormalizedDataBundle):
    """EVT_003：號誌故障 22:30，SOP-5 命中。"""
    as_of = datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI)
    incident = Incident(
        event_id="TPE_2026_EVT_003",
        type="Power_Failure",
        location="松高路/市府路口",
        affected_segment="RD_TPE_007",
        status="Active",
        severity=IncidentSeverity.MEDIUM,
        description="號誌故障",
        timestamp=as_of,
    )
    result = evaluate_rules(bundle, incident=incident)

    clause_ids = {h.clause_id for h in result.rule_hits}
    assert "SOP-5" in clause_ids, "EVT_003 應命中 SOP-5"
    assert "SOP-7" in clause_ids, "EVT_003 應命中 SOP-7"

    # RD_TPE_007 at 22:30 sat=0.85 → B級
    sop1_007 = [h for h in result.rule_hits if h.clause_id == "SOP-1" and h.segment_id == "RD_TPE_007"]
    assert len(sop1_007) >= 1
    # 確認是 B 級（0.85 <= sat < 0.95）
    assert sop1_007[0].evidence.value == 0.85


# -- P5 determine_level 單元測試 --
def test_determine_level_a():
    hits = [RuleHit(clause_id="SOP-1", segment_id="X", evidence=EvidenceRef(field="saturation_score", value=0.98, threshold=0.95))]
    assert determine_level(hits) == "A"


def test_determine_level_b():
    hits = [RuleHit(clause_id="SOP-1", segment_id="X", evidence=EvidenceRef(field="saturation_score", value=0.90, threshold=0.85))]
    assert determine_level(hits) == "B"


def test_determine_level_normal():
    hits = [RuleHit(clause_id="SOP-3", station_id="X", evidence=EvidenceRef(field="user_count", value=30000, threshold=25000))]
    assert determine_level(hits) == "normal"


from src.models import RuleHit, EvidenceRef
