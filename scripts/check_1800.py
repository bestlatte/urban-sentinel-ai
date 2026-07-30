import json

with open('data/city_traffic_flow.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=== 18:00 的所有路段 ===\n")

for d in data:
    if '18:00' in d.get('Timestamp', ''):
        sat = d.get('Saturation_Score', 0)
        level = 'A' if sat >= 0.95 else ('B' if sat >= 0.85 else 'normal')
        print(f"{d['Segment_ID']:12} | {d['Road_Name']:12} | 飽和度={sat:.2f} | 等級={level}")
