"""測試事件分類與路網規劃（含排除原因診斷）"""
from src.orchestrator import classify_incident, build_gateway
from src.models import Incident, IncidentSeverity
from datetime import datetime, timezone, timedelta
import src.orchestrator as orch

# 初始化 GATEWAY
orch.GATEWAY = build_gateway()

tz = timezone(timedelta(hours=8))
bundle = orch.GATEWAY.load_data()

# 先看路網拓樸
print('=== 路網拓樸 ===')
for seg in bundle.road_network:
    print(f'{seg.segment_id}: {seg.name}')
    print(f'  alternatives: {seg.alternatives}')
    print(f'  intersections: {seg.intersections}')
    print()

test_cases = [
    ('Road_Collapse_Accident', 'RD_TPE_006', '敦化南路塌陷'),
    ('Traffic_Accident', 'RD_TPE_003', '基隆路車禍'),
    ('Vehicle_Fire', 'RD_TPE_007', '松高路火警'),
]

print('=== 路網規劃詳細診斷 ===')
from src.routing import plan_route
from src.models import RouteRequest

for event_type, segment, desc in test_cases:
    print(f'\n--- {desc} (事故路段: {segment}) ---')
    
    # 找出事故路段資訊
    affected_seg = next((s for s in bundle.road_network if s.segment_id == segment), None)
    if affected_seg:
        print(f'事故路段 intersections: {affected_seg.intersections}')
        print(f'事故路段 alternatives: {affected_seg.alternatives}')
    
    incident = Incident(
        event_id='TEST_001',
        type=event_type,
        location='測試位置',
        affected_segment=segment,
        status='Closed',
        severity=IncidentSeverity.CRITICAL,
        description='測試',
        timestamp=datetime(2026, 5, 20, 22, 0, tzinfo=tz),
    )
    
    request = RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp)
    route_plan = plan_route(request)
    
    primary = route_plan.primary.name if route_plan.primary else "無"
    secondary = route_plan.secondary.name if route_plan.secondary else "無"
    print(f'結果: 主路線={primary}, 次路線={secondary}')
    
    print('排除的候選:')
    for exc in route_plan.excluded:
        print(f'  {exc.segment_id} ({exc.name}): {exc.reason_code}')
