"""對應 m2-incident-routing/模組2C 第8節驗收測試(AC-C01~C10)，含真實路網資料驗證：
RD_TPE_004容量2500/RD_TPE_005容量4000/RD_TPE_008容量600(排除)/RD_TPE_006非直接相交(排除)。
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.loaders import load_data
from src.models import (
    Incident,
    IncidentSeverity,
    NormalizedDataBundle,
    RouteRequest,
)
from src.routing import plan_route, count_affected_intersections

_TZ_TAIPEI = timezone(timedelta(hours=8))


@pytest.fixture
def bundle() -> NormalizedDataBundle:
    return load_data()


def _make_acc001(bundle):
    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="光復南路/忠孝東路口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="路面塌陷",
        timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI),
    )
    return RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp)


# -- AC-C01: 容量不足道路正確排除 --
def test_capacity_insufficient_excluded(bundle: NormalizedDataBundle):
    """RD_TPE_008 cap=600 應被排除，reason_code=CAPACITY_INSUFFICIENT。"""
    req = _make_acc001(bundle)
    result = plan_route(req)
    excluded_ids = {e.segment_id: e.reason_code for e in result.excluded}
    assert "RD_TPE_008" in excluded_ids
    assert excluded_ids["RD_TPE_008"] == "CAPACITY_INSUFFICIENT"


# -- AC-C02: 非直接相交道路正確排除 --
def test_not_directly_intersecting_excluded(bundle: NormalizedDataBundle):
    """RD_TPE_006 不在 RD_TPE_002 的 intersections 中，應排除。"""
    req = _make_acc001(bundle)
    result = plan_route(req)
    excluded_ids = {e.segment_id: e.reason_code for e in result.excluded}
    assert "RD_TPE_006" in excluded_ids
    assert excluded_ids["RD_TPE_006"] == "NOT_DIRECTLY_INTERSECTING"


# -- 黃金值：主次路線 --
def test_acc_001_golden_route_selection(bundle: NormalizedDataBundle):
    """主RD_TPE_004/次RD_TPE_005。"""
    req = _make_acc001(bundle)
    result = plan_route(req)
    assert result.primary is not None
    assert result.primary.segment_id == "RD_TPE_004"
    assert result.secondary is not None
    assert result.secondary.segment_id == "RD_TPE_005"
    assert result.no_feasible_route is False


# -- AC-C07: 只使用事件時間以前的快照 --
def test_as_of_snapshot_constraint(bundle: NormalizedDataBundle):
    """所有候選的 snapshot_at 都必須 <= as_of。"""
    req = _make_acc001(bundle)
    result = plan_route(req)
    for c in result.candidates:
        if c.snapshot_at is not None:
            assert c.snapshot_at <= req.as_of, (
                f"{c.segment_id} snapshot_at={c.snapshot_at} > as_of={req.as_of}"
            )


# -- AC-C08: 相同輸入產生相同結果 --
def test_deterministic(bundle: NormalizedDataBundle):
    req = _make_acc001(bundle)
    r1 = plan_route(req)
    r2 = plan_route(req)
    assert r1.primary.segment_id == r2.primary.segment_id
    assert r1.secondary.segment_id == r2.secondary.segment_id
    assert len(r1.excluded) == len(r2.excluded)


# -- AC-C10: 計算低於 2 秒 --
def test_performance_under_2_seconds(bundle: NormalizedDataBundle):
    import time
    req = _make_acc001(bundle)
    start = time.perf_counter()
    plan_route(req)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"plan_route took {elapsed:.3f}s, exceeds 2s SLA"


# -- ReasonCode 用 SPEC-00 的 UPPER_SNAKE_CASE --
def test_reason_code_uses_spec00_nine_values_upper_snake_case(bundle: NormalizedDataBundle):
    """所有 excluded 的 reason_code 都必須是九值之一。"""
    from src.models import ReasonCode
    import typing
    valid_codes = set(typing.get_args(ReasonCode))

    req = _make_acc001(bundle)
    result = plan_route(req)
    for e in result.excluded:
        assert e.reason_code in valid_codes, (
            f"{e.segment_id} 的 reason_code '{e.reason_code}' 不在合法九值中"
        )


# -- count_affected_intersections --
def test_count_affected_intersections(bundle: NormalizedDataBundle):
    """RD_TPE_002 有 3 個 intersections。"""
    count = count_affected_intersections(bundle, "RD_TPE_002")
    assert count == 3


def test_count_affected_intersections_unknown_segment(bundle: NormalizedDataBundle):
    """不存在的 segment 回傳 0。"""
    count = count_affected_intersections(bundle, "NONEXISTENT")
    assert count == 0


# ---------------------------------------------------------------------------
# 路線有效性檢查 (check_route_validity) 測試
# ---------------------------------------------------------------------------

from src.routing import check_route_validity, RouteValidityResult


def test_check_route_validity_both_valid(bundle: NormalizedDataBundle):
    """主次路線飽和度都低於 0.85 時，needs_replan=False。"""
    req = _make_acc001(bundle)
    route_plan = plan_route(req)
    
    # ACC_001 事件時間 22:10，主路線 RD_TPE_004 飽和度 0.78，次路線 RD_TPE_005 飽和度 0.65
    result = check_route_validity(route_plan, bundle, req.as_of)
    
    assert result.primary_valid is True
    assert result.secondary_valid is True
    assert result.needs_replan is False
    assert len(result.invalid_reasons) == 0


def test_check_route_validity_primary_saturated(bundle: NormalizedDataBundle):
    """模擬主路線飽和（修改 bundle），needs_replan=True。"""
    req = _make_acc001(bundle)
    route_plan = plan_route(req)
    
    # 建立一個修改過的 bundle，把主路線 RD_TPE_004 的飽和度改成 0.90
    # 複製原有 TrafficSample 並只改 saturation_score
    modified_traffic = []
    for t in bundle.traffic:
        if t.segment_id == "RD_TPE_004" and t.timestamp <= req.as_of:
            # 用 model_copy 保留所有欄位，只改 saturation_score
            modified_t = t.model_copy(update={"saturation_score": 0.90})
            modified_traffic.append(modified_t)
        else:
            modified_traffic.append(t)
    
    modified_bundle = NormalizedDataBundle(
        traffic=modified_traffic,
        crowd=bundle.crowd,
        road_network=bundle.road_network,
        incidents=bundle.incidents,
        sop=bundle.sop,
        loaded_at=bundle.loaded_at,
    )
    
    result = check_route_validity(route_plan, modified_bundle, req.as_of)
    
    assert result.primary_valid is False
    assert result.needs_replan is True
    assert "RD_TPE_004" in result.invalid_reasons
    assert "SATURATED" in result.invalid_reasons["RD_TPE_004"]


def test_check_route_validity_closed_segment(bundle: NormalizedDataBundle):
    """當主路線被新事件封閉時，needs_replan=True。"""
    req = _make_acc001(bundle)
    route_plan = plan_route(req)
    
    # 模擬主路線 RD_TPE_004 被另一個事件封閉
    closed_segments = {"RD_TPE_004"}
    
    result = check_route_validity(route_plan, bundle, req.as_of, closed_segments)
    
    assert result.primary_valid is False
    assert result.needs_replan is True
    assert "RD_TPE_004" in result.invalid_reasons
    assert result.invalid_reasons["RD_TPE_004"] == "CLOSED_BY_NEW_INCIDENT"


def test_check_route_validity_secondary_only_saturated(bundle: NormalizedDataBundle):
    """僅次路線飽和時，needs_replan=True（建議重規劃以找更好的備援）。"""
    req = _make_acc001(bundle)
    route_plan = plan_route(req)
    
    # 把次路線 RD_TPE_005 的飽和度改成 0.88
    modified_traffic = []
    for t in bundle.traffic:
        if t.segment_id == "RD_TPE_005" and t.timestamp <= req.as_of:
            modified_t = t.model_copy(update={"saturation_score": 0.88})
            modified_traffic.append(modified_t)
        else:
            modified_traffic.append(t)
    
    modified_bundle = NormalizedDataBundle(
        traffic=modified_traffic,
        crowd=bundle.crowd,
        road_network=bundle.road_network,
        incidents=bundle.incidents,
        sop=bundle.sop,
        loaded_at=bundle.loaded_at,
    )
    
    result = check_route_validity(route_plan, modified_bundle, req.as_of)
    
    assert result.primary_valid is True
    assert result.secondary_valid is False
    assert result.needs_replan is True
    assert "RD_TPE_005" in result.invalid_reasons
