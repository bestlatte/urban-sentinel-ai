# M2-A：事件接收與生命週期管理——第一階段 Spec

版本：v1.1 Phase 1  
依賴：本地 JSON、SQLite  
不依賴：模組 1、3、4、5

> **[2026-07-28 總架構師補註] Phase 1 → 整合收斂**
> 本文件的 SQLite 儲存與 `/api/incidents*` 系列端點，是**M2 獨立開發期間的沙盒基礎建設**，用途是讓 ling 能不依賴其他模組先把驗證/狀態機/冪等邏輯做完並測試。這些不是最終交付物。
>
> 整合進主系統（`main.py`／`orchestrator.py`）時：
> - 儲存改回 `00-tech-stack.md` §1 規定的「`data/` JSON + Python 記憶體」，不引入 SQLite 做為正式依賴（`IncidentRecord`／狀態歷程／冪等 Key 全部可以用 Python dict/dataclass 存在記憶體，事件量小，不需要資料庫）。
> - `/api/incidents*` 這組端點不會是正式對外 API。正式端點固定是 `00-tech-stack.md` §4 的 4 個（`POST /api/incidents/evaluate` 等），M2 對外只透過函式呼叫（見 M2-B）被 orchestrator 呼叫。
> - 本文件第 3～10 節的驗證規則、狀態機、冪等邏輯**本身完全保留使用**——只是最終承載這些邏輯的不是 SQLite Repository 和獨立端點，而是記憶體物件 + 內部函式呼叫。
> - Definition of Done 裡「SQLite Repository 完成」視為 Phase 1 沙盒驗證用，非整合後的驗收條件。

## 1. 目標

接收、驗證並保存突發事件，維護模組 2獨立處理所需的狀態與分析版本，再將可信的事件交給 M2-B。

## 2. 功能範圍

- 從內建 `live_incidents.json` 選擇事件。
- 上傳單筆或多筆 JSON。
- 手動輸入單筆事件。
- 欄位及道路／場站 ID 驗證。
- 時間正規化為 ISO 8601 `+08:00`。
- SQLite 保存事件、分析版本與狀態歷程。
- Idempotency-Key 防止重複建立。
- 查詢、取消與重新分析。

第一階段不保存 SOP、ETE、Decision Log 或發布結果。

## 3. 輸入

```json
{
  "event_id": "TPE_2026_ACC_001",
  "type": "Road_Collapse_Accident",
  "location": "光復南路與忠孝東路口南側",
  "affected_segment": "RD_TPE_002",
  "affected_road": null,
  "status": "Closed",
  "severity": "Critical",
  "description": "地下管線爆裂導致路面塌陷並引發追撞",
  "timestamp": "2026-05-20 22:10"
}
```

## 4. 驗證規則

| 欄位 | 規則 | 錯誤碼 |
|---|---|---|
| `event_id` | 必填且格式有效 | `INVALID_EVENT_ID` |
| `type` | 必填；未知值可映射為 `other` | `INVALID_EVENT_TYPE` |
| `affected_segment` | 存在於本地道路或場站 ID 集合 | `UNKNOWN_AFFECTED_SEGMENT` |
| `affected_road` | 若提供，須存在於本地路網 | `UNKNOWN_AFFECTED_ROAD` |
| `status` | `Closed/Blocked/Restricted/Caution/Open` | `INVALID_STATUS` |
| `severity` | `Critical/High/Medium/Low` | `INVALID_SEVERITY` |
| `timestamp` | 可解析並轉成 `+08:00` | `INVALID_TIMESTAMP` |
| `description` | 必填且不超過設定長度 | `INVALID_DESCRIPTION` |

驗證失敗不得啟動 A1 或 R1～R5。

## 5. 第一階段狀態機

```text
RECEIVED → VALIDATING → ACCEPTED → CLASSIFYING → PLANNING → COMPLETED
```

錯誤／終止：

```text
VALIDATION_FAILED / PLANNING_FAILED / CANCELLED
```

第一階段不使用 `HANDED_OFF`，因為不交接模組 3／4／5。

## 6. 儲存模型

### IncidentRecord

```json
{
  "event_id": "TPE_2026_ACC_001",
  "request_id": "req_01",
  "analysis_version": 1,
  "processing_status": "ACCEPTED",
  "classification": null,
  "created_by": "demo_commander",
  "created_at": "2026-05-20T22:10:05+08:00",
  "updated_at": "2026-05-20T22:10:05+08:00",
  "source": "builtin",
  "payload": {}
}
```

SQLite 表：

- `incidents`
- `incident_analysis_versions`
- `incident_status_history`
- `idempotency_keys`

原始 JSON 是輸入，不是執行期資料庫，不得直接覆寫。

## 7. API

| 方法 | 路徑 | 用途 |
|---|---|---|
| POST | `/api/incidents` | 建立事件 |
| POST | `/api/incidents/import` | 匯入 JSON |
| GET | `/api/incidents` | 事件清單 |
| GET | `/api/incidents/{event_id}` | 事件、狀態與結果 |
| POST | `/api/incidents/{event_id}/replan` | 建立新分析版本 |
| POST | `/api/incidents/{event_id}/cancel` | 取消處理 |

成功建立：

```json
{
  "event_id": "TPE_2026_ACC_001",
  "request_id": "req_01",
  "analysis_version": 1,
  "processing_status": "ACCEPTED",
  "status_url": "/api/incidents/TPE_2026_ACC_001"
}
```

## 8. 冪等與版本

- 相同 Key 與內容：回傳原請求。
- 相同 Key 但內容不同：`409 IDEMPOTENCY_CONFLICT`。
- 重新分析沿用 `event_id`，遞增 `analysis_version`。
- 舊版輸入、結果與狀態不可被新版覆蓋。

## 9. 驗收條件

- AC-A01：三筆內建事件都可建立並查詢。
- AC-A02：未知道路／場站回傳 422。
- AC-A03：場站事件可搭配 `affected_road`。
- AC-A04：同一 Idempotency-Key 不產生重複事件。
- AC-A05：批次單筆失敗不影響其他有效事件。
- AC-A06：重新分析版本遞增且舊版可查。
- AC-A07：狀態歷程完整且不可非法倒退。

## 10. Definition of Done

- [ ] Pydantic Schema 與驗證完成。
- [ ] 單筆、批次、查詢、取消、重算 API 完成。
- [ ] SQLite Repository 完成。
- [ ] 狀態機、冪等、版本完成。
- [ ] 不依賴外部模組即可通過測試。

