import json

with open('data/city_traffic_flow.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('=== 市民大道四段 (RD_TPE_004) 飽和度變化 ===')
for item in sorted(data, key=lambda x: x['Timestamp']):
    if item['Segment_ID'] == 'RD_TPE_004':
        sat = item['Saturation_Score']
        flag = ' <-- 飽和!' if sat >= 0.85 else ''
        print(f"{item['Timestamp']} -> {sat:.2f}{flag}")

print()
print('=== 仁愛路四段 (RD_TPE_005) 飽和度變化 ===')
for item in sorted(data, key=lambda x: x['Timestamp']):
    if item['Segment_ID'] == 'RD_TPE_005':
        sat = item['Saturation_Score']
        flag = ' <-- 飽和!' if sat >= 0.85 else ''
        print(f"{item['Timestamp']} -> {sat:.2f}{flag}")
