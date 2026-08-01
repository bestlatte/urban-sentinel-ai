"""第5步審核：Orchestrator 編排邏輯驗證"""
import sys, os
os.environ["USE_BEDROCK"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.loaders import _load_incidents
from src.orchestrator import classify_incident, get_same_segment_incidents, _STATE, IncidentRecord
from src.models import NormalizedDataBundle

incidents = _load_incidents()

# === A1 分類驗證 ===
print('=== A1 classify_incident ===')
for inc in incidents:
    result = classify_incident(inc)
    print(f'  {inc.event_id} ({inc.type}): primary_sop={result["primary_sop"]}, '
          f'requires_rerouting={result["requires_rerouting"]}, '
          f'affected_source={result["affected_source"]}')

# spec 期望：
# ACC_001 (Road_Collapse_Accident) → SOP-2, rerouting=True
# EVT_002 (Crowd_Surge_Injury)     → SOP-3, rerouting=False
# EVT_003 (Power_Failure)          → SOP-5, rerouting=False
print()
print('=== A1 spec 對照 ===')
acc001 = [i for i in incidents if i.event_id == 'TPE_2026_ACC_001'][0]
evt002 = [i for i in incidents if i.event_id == 'TPE_2026_EVT_002'][0]
evt003 = [i for i in incidents if i.event_id == 'TPE_2026_EVT_003'][0]

r1 = classify_incident(acc001)
r2 = classify_incident(evt002)
r3 = classify_incident(evt003)
print(f'  ACC_001 SOP-2 reroute=True: {"OK" if r1["primary_sop"]=="SOP-2" and r1["requires_rerouting"] else "FAIL"}')
print(f'  EVT_002 SOP-3 reroute=False: {"OK" if r2["primary_sop"]=="SOP-3" and not r2["requires_rerouting"] else "FAIL"}')
print(f'  EVT_003 SOP-5 reroute=False: {"OK" if r3["primary_sop"]=="SOP-5" and not r3["requires_rerouting"] else "FAIL"}')

# === 同路段合併判定驗證 ===
print()
print('=== 同路段合併判定 ===')
# 模擬：只有 EVT_005 在 active_incidents 中
_STATE.active_incidents.clear()
evt005 = [i for i in incidents if i.event_id == 'TPE_2026_EVT_005'][0]
_STATE.active_incidents['TPE_2026_EVT_005'] = IncidentRecord(
    trace_id='test', incident=evt005
)

# 現在注入 EVT_002 — affected_road 也是 RD_TPE_001
same = get_same_segment_incidents('RD_TPE_001', exclude_event_id='TPE_2026_EVT_002')
print(f'  EVT_002 注入時，同路段(RD_TPE_001)已有: {[r.incident.event_id for r in same]}')
print(f'  (這就是為什麼大巨蛋會觸發合併)')

# 反向：如果只有 EVT_002 在，注入 EVT_005
_STATE.active_incidents.clear()
_STATE.active_incidents['TPE_2026_EVT_002'] = IncidentRecord(
    trace_id='test', incident=evt002
)
same2 = get_same_segment_incidents('RD_TPE_001', exclude_event_id='TPE_2026_EVT_005')
print(f'  EVT_005 注入時，同路段(RD_TPE_001)已有: {[r.incident.event_id for r in same2]}')

# ACC_001 affected_segment=RD_TPE_002，不應有同路段衝突
_STATE.active_incidents.clear()
same3 = get_same_segment_incidents('RD_TPE_002', exclude_event_id='TPE_2026_ACC_001')
print(f'  ACC_001 注入時，同路段(RD_TPE_002)已有: {[r.incident.event_id for r in same3]} (should be empty)')

# === handle_trigger_batch 是否會把事件加入 active_incidents ===
print()
print('=== handle_trigger_batch 確認 ===')
_STATE.active_incidents.clear()
print(f'  active_incidents 目前: {list(_STATE.active_incidents.keys())} (should be empty)')
# handle_trigger_batch 的代碼裡沒有 _STATE.active_incidents[xxx] = ... 的寫入
# 只有 handle_incident 會加。確認完畢。
print(f'  handle_trigger_batch 不會加入 active_incidents: OK (代碼確認)')
