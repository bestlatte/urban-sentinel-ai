"""第4步審核：M4 ETE 計算驗證"""
import sys, os
os.environ["USE_BEDROCK"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.loaders import _load_traffic, _load_crowd, _load_road_network, _load_incidents, _load_sop
from src.models import NormalizedDataBundle
from src.reporting import calculate_ete
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))
traffic = _load_traffic()
crowd = _load_crowd()
road_network, _ = _load_road_network()
incidents = _load_incidents()
sop = _load_sop()
bundle = NormalizedDataBundle(traffic=traffic, crowd=crowd, road_network=road_network, incidents=incidents, sop=sop, loaded_at=datetime.now(tz=TZ))

# === ACC_001: Critical, affected_road=None, affected_segment=RD_TPE_002, sat=1.0 ===
# ETE = 60 + max(0, (1.0 - 0.5) * 60) = 60 + 30 = 90
acc001 = [i for i in incidents if i.event_id == 'TPE_2026_ACC_001'][0]
ete1 = calculate_ete(acc001, bundle)
print('=== ACC_001 (Critical, RD_TPE_002 sat=1.0) ===')
print(f'  ETE: {ete1.minutes} min (expect 90)')
print(f'  formula: {ete1.formula}')
print(f'  base_clearance: {ete1.base_clearance} (expect 60)')
print(f'  avg_saturation: {ete1.average_saturation}')
print()

# === EVT_002: High, affected_road=RD_TPE_001, affected_segment=BS_MRT_BL17 ===
# affected_road 優先 → RD_TPE_001, sat @22:20
# ETE = 40 + max(0, (sat - 0.5) * 60) = ?  spec says 70
evt002 = [i for i in incidents if i.event_id == 'TPE_2026_EVT_002'][0]
ete2 = calculate_ete(evt002, bundle)
print('=== EVT_002 (High, RD_TPE_001) ===')
print(f'  ETE: {ete2.minutes} min (expect 70)')
print(f'  formula: {ete2.formula}')
print(f'  base_clearance: {ete2.base_clearance} (expect 40)')
print(f'  avg_saturation: {ete2.average_saturation}')
print()

# === EVT_003: Medium, affected_segment=RD_TPE_007, sat=0.85 ===
# ETE = 20 + max(0, (0.85 - 0.5) * 60) = 20 + 21 = 41
evt003 = [i for i in incidents if i.event_id == 'TPE_2026_EVT_003'][0]
ete3 = calculate_ete(evt003, bundle)
print('=== EVT_003 (Medium, RD_TPE_007 sat=0.85) ===')
print(f'  ETE: {ete3.minutes} min (expect 41)')
print(f'  formula: {ete3.formula}')
print(f'  base_clearance: {ete3.base_clearance} (expect 20)')
print(f'  avg_saturation: {ete3.average_saturation}')
