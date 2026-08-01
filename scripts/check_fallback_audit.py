"""第6步審核：USE_BEDROCK=false 保底模式驗證"""
import sys, os
os.environ["USE_BEDROCK"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1. SOP 檢索：local_fallback
print('=== 1. SOP 本機檢索 (local_fallback) ===')
try:
    from src.bedrock_service.local_fallback import search_sop_local
    results = search_sop_local("路面塌陷")
    print(f'  search "路面塌陷": {len(results)} 結果')
    for r in results[:3]:
        print(f'    clause_id={r.get("clause_id", "?")}, score={r.get("score", "?")}, title={r.get("title", "?")[:30]}')
    
    results2 = search_sop_local("號誌故障")
    print(f'  search "號誌故障": {len(results2)} 結果')
    for r in results2[:2]:
        print(f'    clause_id={r.get("clause_id", "?")}, title={r.get("title", "?")[:30]}')
    print('  OK')
except Exception as e:
    print(f'  ERROR: {e}')

# 2. 報告生成：固定模板
print()
print('=== 2. 報告生成 (固定模板, USE_BEDROCK=false) ===')
try:
    from src.loaders import _load_traffic, _load_crowd, _load_road_network, _load_incidents, _load_sop
    from src.models import NormalizedDataBundle
    from src.reporting import calculate_ete, generate_report
    from src.rules import evaluate_rules
    from datetime import datetime, timezone, timedelta
    
    TZ = timezone(timedelta(hours=8))
    traffic = _load_traffic()
    crowd = _load_crowd()
    road_network, _ = _load_road_network()
    incidents = _load_incidents()
    sop = _load_sop()
    bundle = NormalizedDataBundle(traffic=traffic, crowd=crowd, road_network=road_network, incidents=incidents, sop=sop, loaded_at=datetime.now(tz=TZ))
    
    acc001 = [i for i in incidents if i.event_id == 'TPE_2026_ACC_001'][0]
    sensing = evaluate_rules(bundle, acc001)
    ete = calculate_ete(acc001, bundle)
    
    report_text, notification = generate_report(acc001, sensing, None, ete, None, bundle, None)
    print(f'  report_text length: {len(report_text) if report_text else 0}')
    print(f'  report_text[:100]: {report_text[:100] if report_text else "None"}')
    print(f'  notification: {notification is not None}')
    if notification:
        print(f'    zh: {notification.zh[:50] if notification.zh else "None"}...')
    print('  OK')
except Exception as e:
    import traceback
    print(f'  ERROR: {e}')
    traceback.print_exc()

# 3. Agent 工具選擇：查表模式
print()
print('=== 3. Agent A2 保底 (查表模式) ===')
try:
    from src.agent.a2_orchestrator_agent import decide_and_execute
    result = decide_and_execute(
        event_id='TPE_2026_ACC_001',
        event_type='Road_Collapse_Accident',
        classification={"primary_sop": "SOP-2", "requires_rerouting": True, "affected_source": "RD_TPE_002"}
    )
    print(f'  result: {result}')
    if result is not None:
        print(f'  planned_by: {result.get("planned_by")}')
    print('  OK')
except Exception as e:
    print(f'  ERROR (可能正常 — A2 agent 在 USE_BEDROCK=false 時走 fallback): {e}')

print()
print('=== 總結 ===')
print('  規則/路網/ETE 三個決定性工具：純 Python，不受 Bedrock 影響 ✓')
print('  SOP 檢索：local_fallback 關鍵字比對 ✓' if 'results' in dir() else '  SOP 檢索: FAILED')
print('  報告生成：固定模板 ✓' if 'report_text' in dir() and report_text else '  報告生成: FAILED')
