# 模組 2 第一階段獨立版 Spec 總覽

版本：v1.1 Phase 1  
狀態：可直接開發  
目標：不依賴模組 1、3、4、5，先完成模組 2 的獨立 Demo

> **[2026-07-28 總架構師補註]** SQLite、`/api/incidents*` 系列端點、模組2專屬 WebSocket，是**本階段獨立開發用的沙盒基礎建設**，不是最終交付物——它們跟 `00-tech-stack.md` 固定的儲存方式（`data/` JSON + 記憶體）與固定 API 表面（4端點+`/ws`）不相容。整合進主系統時的收斂方式見 M2-A／M2-B／M2-D 文件內個別補註；R1-R5 演算法（M2-C）與 A1 分類規則（M2-B）不受影響，正式交付時原樣保留。

## 1. 第一階段交付範圍

## 1. 第一階段交付範圍

```mermaid
flowchart LR
    F3["F3 事件注入"] --> A["M2-A 驗證與保存"]
    A --> A1["A1 本機規則分類"]
    A1 --> R1["R1 載入路網"]
    R1 --> R2["R2 上下游判定"]
    R2 --> R3["R3 候選篩選"]
    R3 --> R4["R4 主次道路"]
    R4 --> R5["R5 原因記錄"]
    R5 --> F4["F4 結果呈現"]
```

第一階段使用本地資料：

| 資料 | 用途 |
|---|---|
| `live_incidents.json` | 事件輸入 |
| `road_network_topology.json` | 路網及替代道路 |
| `city_traffic_flow.json` | as-of 車流快照 |
| SQLite | 執行期事件與分析結果 |

## 2. 子 Spec

| Spec | 功能 | 第一階段結果 |
|---|---|---|
| M2-A | 事件接收與生命週期 | 建立、驗證、儲存、狀態、版本 |
| M2-B | 事件分類與本機流程協調 | A1 規則分類、呼叫 M2-C、組裝結果 |
| M2-C | 本機路網重規劃 | R1～R5、讀本地車流與路網 |
| M2-D | 前端事件操作與呈現 | F3、F4、REST、模組 2內部 WebSocket |

## 3. 第一階段明確不做

- 模組 1即時 API 與跨模組 WebSocket。
- 模組 3 SOP RAG、Embedding、Vector DB。
- 模組 4 ETE、LLM 解釋、Decision Log。
- 模組 5多語通知、人工核准、正式發布。
- Bedrock、Strands Agent、Redis、DynamoDB。
- 真實 GIS 導航。

上述欄位可在輸出保留狀態，但不得用假資料冒充完成：

```json
{
  "integrations": {
    "module1": "LOCAL_JSON_REPLACEMENT",
    "module3": "NOT_CONNECTED",
    "module4": "NOT_CONNECTED",
    "module5": "NOT_CONNECTED"
  }
}
```

## 4. 開發順序與平行工作

- M2-A、M2-C、M2-D 可同時開發。
- M2-D 使用固定 Mock Response，不必等待後端。
- M2-B 先依介面使用 Mock M2-C，之後替換成真實服務。
- 整合順序：M2-A → M2-B ↔ M2-C → M2-D。

## 5. 第一階段完成定義

- [ ] 可注入並驗證事件。
- [ ] 可保存事件與狀態。
- [ ] A1 可用固定規則分類三種事件。
- [ ] 可從本地 JSON 選取 as-of 快照。
- [ ] R1～R5 可產生主次道路與排除理由。
- [ ] F4 能呈現事故及候選道路。
- [ ] 無可行路線時不會虛構答案。
- [ ] 端到端處理時間低於 60 秒。
- [ ] 外部模組未啟用時，模組 2仍能獨立運作。

