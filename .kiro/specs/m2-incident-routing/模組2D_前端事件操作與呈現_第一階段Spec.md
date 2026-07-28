# M2-D：前端事件操作與呈現——第一階段 Spec

版本：v1.1 Phase 1  
對應元件：F3、F4、模組 2內部 WebSocket  
不顯示：SOP、ETE、AI 解釋、多語通知、正式發布

> **[2026-07-28 總架構師補註] Phase 1 → 整合收斂**
> F3／F4 畫面邏輯（第2、3節：輸入模式、SVG 路網呈現、顏色規則）完全保留，跟資料怎麼傳到前端無關。
>
> 第5節「API」表格與第6節「WebSocket」，是 M2 獨立開發期間讓前端能先串接、不必等其他模組完成的臨時契約。整合進主系統後：
> - `POST /api/incidents` 等 7 個端點不存在；F3 送出的事件改走 `POST /api/incidents/evaluate`（`00-tech-stack.md` §4 固定端點），由 orchestrator 內部呼叫 M2 再組裝完整 `DecisionResult` 一次回傳。
> - 推播改走主系統唯一的 `/ws`，訊息格式對齊 `模組間資料流通規格.md` 的 Message Envelope（`message_type` 分派），不是這裡自訂的 `incident.processing.updated` / `incident.route_plan.ready`。
> - F4 畫面需要的欄位（primary_route／secondary_routes／candidate_evaluations／warnings）不變，只是從 `DecisionResult` 裡取，不是從獨立的 `route-plan` 端點取。
>
> 第10節「Mock 情境」的四組假資料非常有價值，正式整合時直接拿來當 M2 的單元測試 fixture（見 `03-testing-and-ai-collaboration.md`），不要丟掉。

## 1. 目標

讓指揮官注入事件、查看模組 2本機處理進度，並在抽象 SVG 路網圖中看見事故道路、主次替代道路及排除理由。

## 2. F3 事件注入

支援：

1. 選擇內建事件。
2. 上傳 JSON。
3. 手動輸入事件。

必備畫面：

- 輸入模式切換。
- 事件預覽。
- 欄位錯誤。
- 送出分析。
- 防止重複提交。
- 處理狀態。
- 取消與重新分析。

表單欄位：`event_id`、`type`、`location`、`affected_segment`、`affected_road`、`status`、`severity`、`description`、`timestamp`。

## 3. F4 路網呈現

因資料沒有座標，第一階段使用抽象 SVG 拓樸圖：

- 紅：事故／封閉道路。
- 綠：主要替代道路。
- 藍：次要道路。
- 灰：排除道路。
- 黃：唯一但已飽和的候選。

點選道路顯示：

- 道路 ID 與名稱。
- 容量。
- 飽和度與快照時間。
- 上下游關係。
- 合格狀態。
- 選用／排除理由。

前端不得重新計算或排序。

## 4. 第一階段流程

```text
F3 輸入
→ POST /api/incidents
→ 顯示 request_id
→ WebSocket 接收 VALIDATING / CLASSIFYING / PLANNING
→ 收到 incident.route_plan.ready
→ F4 顯示結果
→ 狀態 COMPLETED
```

## 5. API

| 操作 | API |
|---|---|
| 建立 | `POST /api/incidents` |
| 上傳 | `POST /api/incidents/import` |
| 查詢 | `GET /api/incidents/{event_id}` |
| 路線 | `GET /api/incidents/{event_id}/route-plan` |
| 重算 | `POST /api/incidents/{event_id}/replan` |
| 取消 | `POST /api/incidents/{event_id}/cancel` |
| 推播 | `/ws` |

## 6. WebSocket

```json
{
  "event": "incident.processing.updated",
  "event_id": "TPE_2026_ACC_001",
  "request_id": "req_01",
  "processing_status": "PLANNING",
  "progress": 70,
  "timestamp": "2026-05-20T22:10:10+08:00"
}
```

完成：

```json
{
  "event": "incident.route_plan.ready",
  "event_id": "TPE_2026_ACC_001",
  "analysis_version": 1,
  "payload": {}
}
```

這是模組 2前後端內部資料流，不是跨模組資料流，因此第一階段保留。

## 7. 斷線策略

- 自動重新連線。
- 斷線期間用 REST 查詢事件狀態。
- 重連後依 `event_id` 重新同步。
- 重複訊息不得建立重複卡片。

## 8. 第一階段畫面不做

- SOP 引用卡。
- ETE 與預計恢復時間。
- AI 決策解釋。
- Decision Log。
- 多語簡訊。
- 核准與發布狀態。

正式 Demo 可直接隱藏，不要顯示空白卡片。開發模式可標示「Phase 2」。

## 9. UI 規則

- `NO_FEASIBLE_ROUTE` 顯示明確文字，不顯示空白。
- `saturated_but_retained` 使用黃色警告。
- 顯示飽和度時同時顯示快照時間。
- 模擬資料顯示 `Demo／Simulated`。
- 不只靠顏色區別狀態，需搭配文字或圖示。
- 後端錯誤對應到具體表單欄位。

## 10. Mock 情境

前端可先建立四組 Mock：

1. 正常成功。
2. 驗證失敗。
3. 無可行道路。
4. 唯一飽和候選。

Mock Response 必須符合正式 API 契約，以便後端完成後直接替換。

## 11. 驗收條件

- AC-D01：三種輸入模式正常。
- AC-D02：欄位錯誤可定位且不能送出。
- AC-D03：狀態依序即時更新。
- AC-D04：事故、主次與排除道路顯示正確。
- AC-D05：道路原因與後端 payload 一致。
- AC-D06：WebSocket 斷線時可改用 REST。
- AC-D07：無路可走與飽和例外提示清楚。
- AC-D08：不出現跨模組空白卡片。

## 12. Definition of Done

- [ ] F3 三種輸入完成。
- [ ] F4 抽象路網完成。
- [ ] 模組 2內部 REST／WebSocket 完成。
- [ ] 斷線 fallback 完成。
- [ ] 四組 Mock 通過。
- [ ] 前端不重算路線或規則。
- [ ] 跨模組功能已隱藏或標示 Phase 2。

