import requests
import json

r = requests.post("http://localhost:8000/api/incidents/evaluate", json={"event_id": "TPE_2026_ACC_001"})
data = r.json()

print("Status:", data.get("status"))
print("Level:", data.get("payload", {}).get("level"))
print("Incident:", json.dumps(data.get("payload", {}).get("incident"), indent=2, ensure_ascii=False))
