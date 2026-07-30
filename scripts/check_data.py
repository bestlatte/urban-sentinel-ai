import json
from collections import defaultdict

with open('data/city_traffic_flow.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 按時間排序，看飽和度變化
by_time = defaultdict(list)
for d in data:
    ts = d.get('Timestamp', '')[:16]  # 取到分鐘
    sat = d.get('Saturation_Score', 0)
    seg = d.get('Segment_ID', '')
    by_time[ts].append((seg, sat))

print("=== 交通資料飽和度分析 ===\n")

# 計算每個時間點的等級
for ts in sorted(by_time.keys()):
    samples = by_time[ts]
    max_sat = max(s[1] for s in samples)
    a_count = sum(1 for s in samples if s[1] >= 0.95)
    b_count = sum(1 for s in samples if 0.85 <= s[1] < 0.95)
    
    level = "normal"
    if a_count > 0:
        level = "A"
    elif b_count > 0:
        level = "B"
    
    print(f'{ts} → 等級={level}, 最高飽和度={max_sat:.2f}, A級路段={a_count}, B級路段={b_count}')
