"""測試路線重規劃功能"""
import requests

BASE = "http://localhost:8000"

# 1. 重設狀態
print("=== 1. 重設後端狀態 ===")
r = requests.post(f"{BASE}/api/reset")
print(r.json())

# 2. 啟動模擬器
print("\n=== 2. 啟動模擬器 ===")
r = requests.post(f"{BASE}/api/simulation/start")
print(r.json())

# 3. 跳到 22:00
print("\n=== 3. 跳到 22:00 (事件發生時間) ===")
r = requests.post(f"{BASE}/api/simulation/seek", json={"time": "22:00"})
print(r.json())

# 4. 觸發 ACC_001 事件
print("\n=== 4. 觸發 ACC_001 事件 ===")
r = requests.post(f"{BASE}/api/incidents/evaluate", json={"event_id": "TPE_2026_ACC_001"})
data = r.json()
if data.get("status") == "ok" and data.get("payload", {}).get("routes"):
    routes = data["payload"]["routes"]
    print(f"主路線: {routes['primary']['segment_id']} ({routes['primary']['name']})")
    print(f"次路線: {routes['secondary']['segment_id']} ({routes['secondary']['name']})")
else:
    print(data)

# 5. 確認事件已在 active_incidents
print("\n=== 5. 確認 Dashboard 狀態 ===")
r = requests.get(f"{BASE}/api/dashboard")
data = r.json()
print(f"活躍事件數: {data['payload']['kpis']['active_incident_count']}")

# 6. 跳到 22:15 - 主路線飽和
print("\n=== 6. 跳到 22:15 (主路線 RD_TPE_004 飽和度達 0.85) ===")
print("請觀察 WebSocket 是否收到 routes.updated.v1 訊息...")
r = requests.post(f"{BASE}/api/simulation/seek", json={"time": "22:15"})
print(r.json())

# 7. 手動觸發一次評估（模擬時間推進後的狀態檢查）
print("\n=== 7. 查看當前 Dashboard ===")
r = requests.get(f"{BASE}/api/dashboard")
data = r.json()
print(f"活躍事件數: {data['payload']['kpis']['active_incident_count']}")

print("\n=== 測試完成 ===")
print("如果 WebSocket 有連接，應該會收到 routes.updated.v1 訊息")
print("打開瀏覽器 DevTools > Network > WS 觀察推播")
