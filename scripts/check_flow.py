import json

with open('data/road_network_topology.json', encoding='utf-8') as f:
    data = json.load(f)

for seg in data:
    print(f"{seg['segment_id']} {seg['name']}: {seg['flow_direction']}")
