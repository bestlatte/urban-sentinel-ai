"""第3步審核：M2 路網規劃驗證"""
import sys, os
os.environ["USE_BEDROCK"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.loaders import _load_traffic, _load_crowd, _load_road_network, _load_incidents, _load_sop
from src.models import NormalizedDataBundle, RouteRequest
from src.routing import plan_route
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
traffic = _load_traffic()
crowd = _load_crowd()
road_network, _ = _load_road_network()
incidents = _load_incidents()
sop = _load_sop()
bundle = NormalizedDataBundle(traffic=traffic, crowd=crowd, road_network=road_network, incidents=incidents, sop=sop, loaded_at=datetime.now(tz=TZ))

acc001 = [i for i in incidents if i.event_id == 'TPE_2026_ACC_001'][0]
req = RouteRequest(incident=acc001, bundle=bundle, as_of=acc001.timestamp)
plan = plan_route(req)

print('=== ACC_001 路網規劃 ===')
print(f'  primary: {plan.primary.segment_id if plan.primary else None} ({plan.primary.name if plan.primary else None})')
print(f'  secondary: {plan.secondary.segment_id if plan.secondary else None} ({plan.secondary.name if plan.secondary else None})')
print(f'  no_feasible: {plan.no_feasible_route}')
print(f'  excluded:')
for e in plan.excluded:
    print(f'    {e.segment_id} ({e.name}): {e.reason_code} sat={e.saturation_score} cap={e.capacity_vph}')
print(f'  findings: {[(f.finding_code, f.segment_ids) for f in plan.findings]}')
print(f'  all candidates:')
for c in plan.candidates:
    print(f'    {c.segment_id} ({c.name}): eligible={c.eligible} reason={c.reason_code} sat={c.saturation_score} cap={c.capacity_vph}')

# spec 期望：主=RD_TPE_004(市民大道四段) 次=RD_TPE_005(仁愛路四段)
# RD_TPE_006 非直接相交排除, RD_TPE_008(延吉街) 容量600排除
print('\n=== spec 期望對照 ===')
print(f'  primary 期望 RD_TPE_004: {"OK" if plan.primary and plan.primary.segment_id == "RD_TPE_004" else "MISMATCH"}')
print(f'  secondary 期望 RD_TPE_005: {"OK" if plan.secondary and plan.secondary.segment_id == "RD_TPE_005" else "MISMATCH"}')
