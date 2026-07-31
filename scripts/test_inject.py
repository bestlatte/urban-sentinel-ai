import requests

# 重設
r = requests.post('http://localhost:8000/api/reset')
print('Reset:', r.json())

# 注入事件
r = requests.post('http://localhost:8000/api/incidents/evaluate', json={'event_id': 'TPE_2026_ACC_001'})
data = r.json()
print('Status:', data['status'])
print('Level:', data['payload']['level'])
print('Incident event_id:', data['payload']['incident']['event_id'])
