from src.loaders import load_data
from datetime import datetime, timezone, timedelta

bundle = load_data()
tz = timezone(timedelta(hours=8))
as_of = datetime(2026, 5, 20, 22, 10, tzinfo=tz)

# 看 22:10 之前最近的飽和度
targets = ['RD_TPE_004', 'RD_TPE_005', 'RD_TPE_006']
for seg_id in targets:
    samples = [t for t in bundle.traffic if t.segment_id == seg_id and t.timestamp <= as_of]
    if samples:
        best = max(samples, key=lambda t: t.timestamp)
        seg = next((s for s in bundle.road_network if s.segment_id == seg_id), None)
        name = seg.name if seg else seg_id
        print(f'{name}: sat={best.saturation_score}, time={best.timestamp.strftime("%H:%M")}')
    else:
        print(f'{seg_id}: 無資料')
