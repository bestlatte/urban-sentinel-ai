"""檢查事件時間清單"""
from src.loaders import load_data

bundle = load_data()

# 列出所有事件及其時間
print('=== 事件時間清單（按時間排序）===')
incidents = sorted(bundle.incidents, key=lambda x: x.timestamp)
for inc in incidents:
    ts = inc.timestamp.strftime('%H:%M') if inc.timestamp else 'N/A'
    print(f'{ts} | {inc.severity.value:8} | {inc.event_id} | {inc.description[:35]}...')
