"""測試 API 序列化後的 DecisionResult 結構"""
import os
os.environ['USE_BEDROCK'] = 'false'

from src.loaders import load_data
from src.rules import evaluate_rules
from src.routing import plan_route
from src.reporting import calculate_ete, generate_report
from src.models import RouteRequest, DecisionResult, Notification
import asyncio

async def main():
    # 模擬 orchestrator.handle_incident 的流程
    from src.orchestrator import handle_incident, build_gateway, GATEWAY
    import src.orchestrator as orch
    
    # 初始化 GATEWAY
    orch.GATEWAY = build_gateway()
    
    bundle = orch.GATEWAY.load_data()
    incident = next((i for i in bundle.incidents if i.event_id == 'TPE_2026_ACC_001'), None)
    
    if not incident:
        print('找不到事件')
        return
    
    # 呼叫 handle_incident
    decision_result = await handle_incident(incident)
    
    # 序列化成 JSON（跟 main.py 一樣）
    payload_json = decision_result.model_dump(mode="json")
    
    import json
    print("=== API Response (JSON) ===")
    print(json.dumps(payload_json, indent=2, ensure_ascii=False))
    
    print("\n=== notifications 欄位 ===")
    print(f"notifications: {payload_json.get('notifications')}")
    
    print("\n=== control_center_report 欄位 ===")
    print(f"control_center_report: {payload_json.get('control_center_report')}")

asyncio.run(main())
