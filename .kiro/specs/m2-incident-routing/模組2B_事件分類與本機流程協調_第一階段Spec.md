# M2-B：事件分類與本機流程協調——第一階段 Spec

版本：v1.1 Phase 1  
依賴：M2-A、M2-C  
不依賴：Agent、Bedrock、模組 1、3、4、5

> **[2026-07-28 總架構師補註] Phase 1 → 整合收斂**
> A1 分類規則與 `LocalModule2Coordinator` 的邏輯（第3、4節）完全保留，這是 M2 的核心價值，跟儲存/傳輸方式無關。
>
> 第6節「模組2內部介面」中「M2-B → M2-D：透過 REST Response 與模組 2自己的 WebSocket」，整合後改為：`LocalModule2Coordinator.process_incident()` 直接是 orchestrator.py 呼叫的 Python 函式，實際簽章對齊 `src/orchestrator.py` 的 `ModuleGateway.plan_routes(request: RouteRequest) -> RoutePlan`（[2026-07-28再更正] 原寫 `routing.plan_route(incident, as_of) -> Module2Result`，是第三種跟其他地方都不一樣的簽章，已統一），結果透過 orchestrator 組裝進 `DecisionResult`，用主系統唯一的 `POST /api/incidents/evaluate` 回傳與唯一的 `/ws` 推播送出，不會有「模組2自己的 WebSocket」。
>
> 這代表 Phase 1 完成後，`process_incident()` 這個函式簽章是跟其他模組對接的正式邊界，其餘 REST／WebSocket 包裝都是開發期間用來獨立驗證這個函式的臨時介面，不隨 M2 一起交付進主系統。

## 1. 目標

用固定規則分類 M2-A 驗證完成的事件，判斷是否需要路網規劃，呼叫 M2-C，組裝模組 2獨立結果並更新事件狀態。

## 2. 第一階段流程

```text
IncidentRecord
→ A1 規則分類
→ 判斷 affected_road
→ 呼叫 M2-C
→ 收集 RoutePlanResult
→ 組裝 Module2Result
→ 更新 COMPLETED
```

## 3. A1 分類規則

| `type` | 分類 | 是否規劃道路 |
|---|---|---:|
| `Road_Collapse_Accident` | `road_disruption` | 是 |
| `Crowd_Surge_Injury` | `crowd_incident` | 有 `affected_road` 時 |
| `Power_Failure` | `signal_failure` | 有道路 ID 時 |
| 其他 | `other` | 否，等待人工確認 |

A1 是 Python 規則，不使用 LLM。

輸出：

```json
{
  "classification": "road_disruption",
  "requires_route_planning": true,
  "planning_road": "RD_TPE_002",
  "needs_human_review": false
}
```

## 4. LocalModule2Coordinator

建議介面：

```python
process_incident(incident_record) -> Module2Result
```

概念流程：

```python
classification = classifier.classify(incident)
route_plan = None

if classification.requires_route_planning:
    route_plan = route_planner.plan(incident)

return Module2Result(
    incident=incident,
    classification=classification,
    route_plan=route_plan,
)
```

## 5. 獨立版輸出

```json
{
  "event_id": "TPE_2026_ACC_001",
  "request_id": "req_01",
  "analysis_version": 1,
  "processing_status": "COMPLETED",
  "classification": {
    "type": "road_disruption",
    "requires_route_planning": true
  },
  "route_plan": {},
  "data_sources": {
    "incident": "LOCAL_JSON",
    "road_network": "LOCAL_JSON",
    "traffic": "LOCAL_JSON"
  },
  "integrations": {
    "module1": "LOCAL_JSON_REPLACEMENT",
    "module3": "NOT_CONNECTED",
    "module4": "NOT_CONNECTED",
    "module5": "NOT_CONNECTED"
  }
}
```

不得填入假的 SOP、ETE 或發布結果。

## 6. 模組 2內部介面

### M2-A → M2-B

輸入 `IncidentRecord`，狀態必須是 `ACCEPTED`。

### M2-B → M2-C

```json
{
  "event_id": "TPE_2026_ACC_001",
  "analysis_version": 1,
  "affected_road": "RD_TPE_002",
  "event_timestamp": "2026-05-20T22:10:00+08:00",
  "status": "Closed",
  "severity": "Critical"
}
```

### M2-B → M2-D

透過 REST Response 與模組 2自己的 WebSocket 傳送狀態和最終 `Module2Result`。

## 7. 狀態與錯誤

```text
ACCEPTED → CLASSIFYING → PLANNING → COMPLETED
```

- 未知事件且無法規劃：可完成分類，`route_plan=null`，並標記需人工確認。
- M2-C 失敗：`PLANNING_FAILED`，保存錯誤與可重試狀態。
- 找不到道路：不得呼叫 M2-C，回傳結構化錯誤。
- WebSocket 失效不影響後端處理。

## 8. 第一階段不做

- 不呼叫模組 1 API。
- 不查 SOP DB。
- 不呼叫模組 4算 ETE。
- 不產生多語通知。
- 不使用 Agent Orchestrator。

未來整合點只保留介面狀態，不影響第一階段完成條件。

## 9. 驗收條件

- AC-B01：道路塌陷正確分類並呼叫 M2-C。
- AC-B02：人流事件只有存在 `affected_road` 才規劃道路。
- AC-B03：號誌故障以受影響道路進行規劃。
- AC-B04：未知事件不由 LLM 猜測，標記人工確認。
- AC-B05：M2-C 成功後組裝完整獨立版結果。
- AC-B06：外部模組全部不可用時仍能完成。

## 10. Definition of Done

- [ ] A1 決定性分類完成。
- [ ] LocalModule2Coordinator 完成。
- [ ] M2-A 與 M2-C 串接完成。
- [ ] 狀態與錯誤處理完成。
- [ ] 獨立版 Module2Result 完成。
- [ ] 無任何外部模組或雲端依賴。

