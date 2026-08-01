"""檢查光復南路的上下游判定（含車流方向）"""
from src.loaders import load_data
from src.routing import _determine_position, _parse_flow_direction

bundle = load_data()

# 光復南路
affected = next(s for s in bundle.road_network if s.segment_id == 'RD_TPE_002')
print(f"光復南路 flow_direction: {affected.flow_direction}")
print(f"光復南路 intersections: {affected.intersections}")
print(f"光復南路 alternatives: {affected.alternatives}")

base, flow = _parse_flow_direction(affected.flow_direction)
print(f"解析結果: 基本方向={base}, 受影響車流={flow}")
print()

# 檢查每個候選的位置
for alt_id in affected.alternatives:
    seg = next((s for s in bundle.road_network if s.segment_id == alt_id), None)
    if seg:
        name = seg.name
        # 判定位置
        if name in affected.intersections:
            position = _determine_position(name, affected.intersections, affected.flow_direction)
        else:
            position = "parallel（平行替代）"
        print(f"{name}: {position}")
