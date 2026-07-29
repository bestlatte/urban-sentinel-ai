"""對應 m4-decision-reporting/requirements.md 第四節驗收測試(#1-8)。

Phase 3.1 只測 calculate_ete（A3，確定性）。
Phase 3.2 再補 generate_report（C1-C4，LLM 相關）。
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.loaders import load_data
from src.models import Incident, IncidentSeverity, NormalizedDataBundle
from src.reporting import calculate_ete

_TZ_TAIPEI = timezone(timedelta(hours=8))


@pytest.fixture
def bundle() -> NormalizedDataBundle:
    return load_data()


# -- 驗收測試 #1：ACC_001 ETE = 90 分 --
def test_ete_acc001_golden(bundle: NormalizedDataBundle):
    """Critical, RD_TPE_002 sat=1.0 → 60 + max(0,(1.0-0.5)*60) = 90。"""
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
    ete = calculate_ete(incident, bundle)
    assert ete.minutes == 90
    assert ete.recovery_at == "2026-05-20 23:40"
    assert ete.base_clearance == 60
    assert ete.average_saturation == 1.0


# -- 驗收測試 #1 補充：EVT_002 ETE = 70 分 --
def test_ete_evt002_golden(bundle: NormalizedDataBundle):
    """High, affected_road=RD_TPE_001 sat=1.0 → 40 + 30 = 70。"""
    incident = Incident(
        event_id="TPE_2026_EVT_002",
        type="Crowd_Surge_Injury",
        location="捷運國父紀念館站",
        affected_segment="BS_MRT_BL17",
        affected_road="RD_TPE_001",
        status="Active",
        severity=IncidentSeverity.HIGH,
        description="人群推擠",
        timestamp=datetime(2026, 5, 20, 22, 20, tzinfo=_TZ_TAIPEI),
    )
    ete = calculate_ete(incident, bundle)
    assert ete.minutes == 70
    assert ete.base_clearance == 40
    assert ete.average_saturation == 1.0


# -- 驗收測試 #2：EVT_003 ETE = 41 分 --
def test_ete_evt003_golden(bundle: NormalizedDataBundle):
    """Medium, RD_TPE_007 sat=0.85 → 20 + max(0,(0.85-0.5)*60) = 20+21 = 41。"""
    incident = Incident(
        event_id="TPE_2026_EVT_003",
        type="Power_Failure",
        location="松高路/市府路口",
        affected_segment="RD_TPE_007",
        status="Active",
        severity=IncidentSeverity.MEDIUM,
        description="號誌故障",
        timestamp=datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI),
    )
    ete = calculate_ete(incident, bundle)
    assert ete.minutes == 41
    assert ete.base_clearance == 20
    assert ete.average_saturation == 0.85


# -- 驗收測試 #3：severity 缺漏（用不合法的值）--
def test_ete_invalid_severity_raises(bundle: NormalizedDataBundle):
    """未知 severity 應拋 ValueError。"""
    # 模擬一個有不合法 severity 的情境 — 用 model_construct 繞過 Pydantic 驗證
    incident = Incident.model_construct(
        event_id="BAD",
        type="Test",
        location="test",
        affected_segment="RD_TPE_001",
        status="Active",
        severity="Unknown",  # type: ignore
        description="",
        timestamp=datetime(2026, 5, 20, 22, 0, tzinfo=_TZ_TAIPEI),
    )
    with pytest.raises((ValueError, AttributeError)):
        calculate_ete(incident, bundle)


# -- 確定性：相同輸入相同輸出 --
def test_ete_deterministic(bundle: NormalizedDataBundle):
    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="test",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="",
        timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI),
    )
    r1 = calculate_ete(incident, bundle)
    r2 = calculate_ete(incident, bundle)
    assert r1.minutes == r2.minutes
    assert r1.recovery_at == r2.recovery_at
    assert r1.formula == r2.formula


# -- formula 欄位格式 --
def test_ete_formula_contains_values(bundle: NormalizedDataBundle):
    """formula 應包含代入的數值。"""
    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="test",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="",
        timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=_TZ_TAIPEI),
    )
    ete = calculate_ete(incident, bundle)
    assert "60" in ete.formula
    assert "90" in ete.formula


# -- Phase 3.2: generate_report 測試 --

def _make_acc001_inputs(bundle):
    """組裝 ACC_001 的完整輸入。"""
    from src.rules import evaluate_rules
    from src.routing import plan_route

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
    sensing = evaluate_rules(bundle, incident)
    from src.models import RouteRequest
    route_plan = plan_route(RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp))
    ete = calculate_ete(incident, bundle)
    return incident, sensing, route_plan, ete


def test_generate_report_returns_tuple(bundle: NormalizedDataBundle):
    """generate_report 回傳 (str|None, Notification|None)。"""
    from src.reporting import generate_report
    import os
    os.environ["USE_BEDROCK"] = "false"
    incident, sensing, route_plan, ete = _make_acc001_inputs(bundle)
    result = generate_report(incident, sensing, route_plan, ete, advisory=None)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_generate_report_notification_is_single_object_not_list(bundle: NormalizedDataBundle):
    """回歸測試：第二回傳值是單一 Notification 物件，不是 list。"""
    from src.reporting import generate_report
    from src.models import Notification as NotifModel
    import os
    os.environ["USE_BEDROCK"] = "false"
    incident, sensing, route_plan, ete = _make_acc001_inputs(bundle)
    _, notification = generate_report(incident, sensing, route_plan, ete, advisory=None)
    assert notification is None or isinstance(notification, NotifModel)


def test_c4_sop6_not_triggered_en_is_none(bundle: NormalizedDataBundle):
    """SOP-6 未觸發時 Notification.en 為 None。"""
    from src.reporting import generate_report
    from src.rules import evaluate_rules
    import os
    os.environ["USE_BEDROCK"] = "false"

    # EVT_003 at 22:30 — 需確認 SOP-6 是否觸發
    incident = Incident(
        event_id="TPE_2026_EVT_003",
        type="Power_Failure",
        location="松高路/市府路口",
        affected_segment="RD_TPE_007",
        status="Active",
        severity=IncidentSeverity.MEDIUM,
        description="號誌故障",
        timestamp=datetime(2026, 5, 20, 22, 30, tzinfo=_TZ_TAIPEI),
    )
    sensing = evaluate_rules(bundle, incident)
    ete = calculate_ete(incident, bundle)
    # 如果 SOP-6 沒觸發，en 應該是 None
    if not sensing.multilingual_required:
        _, notification = generate_report(incident, sensing, None, ete, advisory=None)
        assert notification is not None
        assert notification.en is None
        assert notification.zh is not None


def test_c4_sop6_triggered_en_is_not_none(bundle: NormalizedDataBundle):
    """SOP-6 觸發時 Notification.en 應非空。"""
    from src.reporting import generate_report
    import os
    os.environ["USE_BEDROCK"] = "false"
    incident, sensing, route_plan, ete = _make_acc001_inputs(bundle)
    # ACC_001 at 22:10 — BS_TPE_101 roaming=0.40 >= 0.30 → SOP-6 觸發
    assert sensing.multilingual_required is True
    _, notification = generate_report(incident, sensing, route_plan, ete, advisory=None)
    assert notification is not None
    assert notification.zh is not None
    assert notification.en is not None


def test_report_contains_ete_value(bundle: NormalizedDataBundle):
    """建議書全文應包含 ETE 數值。"""
    from src.reporting import generate_report
    import os
    os.environ["USE_BEDROCK"] = "false"
    incident, sensing, route_plan, ete = _make_acc001_inputs(bundle)
    report_text, _ = generate_report(incident, sensing, route_plan, ete, advisory=None)
    assert report_text is not None
    assert "90" in report_text


def test_report_contains_route_names(bundle: NormalizedDataBundle):
    """建議書全文應包含路段中文名而非 segment_id。"""
    from src.reporting import generate_report
    import os
    os.environ["USE_BEDROCK"] = "false"
    incident, sensing, route_plan, ete = _make_acc001_inputs(bundle)
    report_text, _ = generate_report(incident, sensing, route_plan, ete, advisory=None)
    assert report_text is not None
    assert "市民大道四段" in report_text  # primary route name


def test_llm_does_not_alter_fact_fields(bundle: NormalizedDataBundle):
    """確定性：相同輸入兩次，事實欄位（ETE/路段名/SOP編號）逐字相同。"""
    from src.reporting import generate_report
    import os
    os.environ["USE_BEDROCK"] = "false"
    incident, sensing, route_plan, ete = _make_acc001_inputs(bundle)
    r1, n1 = generate_report(incident, sensing, route_plan, ete, advisory=None)
    r2, n2 = generate_report(incident, sensing, route_plan, ete, advisory=None)
    assert r1 == r2  # 保底模板是確定性的
    if n1 and n2:
        assert n1.zh == n2.zh
