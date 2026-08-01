"""檢查光復南路事件的路網規劃結果"""
from src.orchestrator import build_gateway
from src.models import Incident, IncidentSeverity, RouteRequest
from src.routing import plan_route, _determine_position, _is_directly_intersecting
from datetime import datetime, timezone, timedelta
import src.orchestrator as orch

orch.GATEWAY = build_gateway()
bundle = orch.GATEWAY.load_data()

tz = timezone(timedelta(hours=8))
incident = Incident(
    event_id='TPE_2026_ACC_001',
    type='Road_Collapse_Accident',
    location='光復南路與忠孝東路口南側',
    affected_segment='RD_TPE_002',
    status='Closed',
    severity=IncidentSeverity.CRITICAL,
    description='路面塌陷',
    timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=tz),
)

# 先看位置分類
affected_seg = next(s for s in bundle.road_network if s.segment_id == 'RD_TPE_002')
print("=== 候選路線位置分類 ===")
print(f"事故路段: {affected_seg.name}")
print(f"車流方向: {affected_seg.flow_direction}")
print()

for alt_id in affected_seg.alternatives:
    seg = next((s for s in bundle.road_network if s.segment_id == alt_id), None)
    if seg:
        if _is_directly_intersecting(seg.name, affected_seg.intersections):
            pos = _determine_position(seg.name, affected_seg.intersections, affected_seg.flow_direction)
        else:
            pos = "parallel"
        print(f"  {seg.name}: {pos}")

print()

request = RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp)
route_plan = plan_route(request)

print("=== 路網規劃結果 ===")
print(f"主路線: {route_plan.primary.name if route_plan.primary else '無'} (sat={route_plan.primary.saturation_score if route_plan.primary else '-'})")
print(f"次路線: {route_plan.secondary.name if route_plan.secondary else '無'} (sat={route_plan.secondary.saturation_score if route_plan.secondary else '-'})")
print()
print("排序說明:")
print("  - 上游(upstream) + 平行(parallel) 優先")
print("  - 下游(downstream) 次之")
print("  - 同組內按飽和度低、容量高排序")
