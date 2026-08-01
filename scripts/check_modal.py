"""測試 Modal 顯示的資料是否正確"""
import os
os.environ['USE_BEDROCK'] = 'false'

from src.loaders import load_data
from src.rules import evaluate_rules
from src.routing import plan_route
from src.reporting import calculate_ete, generate_report
from src.models import RouteRequest

bundle = load_data()

# 找到 ACC_001 事件
incident = next((i for i in bundle.incidents if i.event_id == 'TPE_2026_ACC_001'), None)
if not incident:
    print('找不到事件')
    exit()

print(f'事件: {incident.event_id}')
print(f'時間: {incident.timestamp}')

sensing = evaluate_rules(bundle, incident)
print(f'multilingual_required: {sensing.multilingual_required}')
print(f'rule_hits: {[h.clause_id for h in sensing.rule_hits]}')

# 看 SOP-6 細節
sop6_hits = [h for h in sensing.rule_hits if h.clause_id == 'SOP-6']
print(f'SOP-6 命中數: {len(sop6_hits)}')
for h in sop6_hits:
    print(f'  - {h.segment_id}: {h.evidence}')

# ETE
ete = calculate_ete(incident, bundle)
print(f'ETE: {ete.minutes} 分鐘')

# 路線
route_plan = plan_route(RouteRequest(incident=incident, bundle=bundle, as_of=incident.timestamp))

# 生成報告
report_text, notification = generate_report(incident, sensing, route_plan, ete, advisory=None, bundle=bundle)

print('---')
print(f'report_text 長度: {len(report_text) if report_text else 0}')
if report_text:
    print('report_text 內容:')
    print(report_text)
print('---')
if notification:
    print(f'notification.zh: {notification.zh}')
    print(f'notification.en: {notification.en}')
    print(f'notification.ja: {notification.ja}')
    print(f'notification.ko: {notification.ko}')
else:
    print('notification is None!')
