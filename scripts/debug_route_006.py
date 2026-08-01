"""Debug: 為何 RD_TPE_006 沒有可用替代路線"""
from src.loaders import load_data
from src.routing import plan_route
from src.models import RouteRequest, Incident
from datetime import datetime, timezone, timedelta

bundle = load_data()

# 台北時區
TPE = timezone(timedelta(hours=8))

# TPE_2026_ACC_010 - RD_TPE_006 敦化南路
incident = Incident(
    event_id='TPE_2026_ACC_010',
    type='Road_Collapse_Accident',
    location='敦化南路一段與忠孝東路口',
    affected_segment='RD_TPE_006',
    status='Closed',
    severity='Critical',
    description='自來水管線破裂造成路面下陷，雙向封閉搶修中',
    timestamp=datetime(2026, 5, 20, 22, 50, tzinfo=TPE)
)

request = RouteRequest(incident=incident, bundle=bundle, as_of=datetime(2026, 5, 20, 22, 50, tzinfo=TPE))
result = plan_route(request)

print('=== RD_TPE_006 alternatives ===')
segment_map = {s.segment_id: s for s in bundle.road_network}
affected = segment_map['RD_TPE_006']
print(f'Alternatives: {affected.alternatives}')

print()
print('=== Candidates ===')
for c in result.candidates:
    print(f'{c.segment_id} ({c.name}): eligible={c.eligible}, reason={c.reason_code}, sat={c.saturation_score}')

print()
print(f'Primary: {result.primary}')
print(f'Secondary: {result.secondary}')
print(f'no_feasible_route: {result.no_feasible_route}')
