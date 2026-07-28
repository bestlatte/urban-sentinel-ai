# SPEC-O1 Orchestrator：決策週期生命週期 — v1

> 依賴：SPEC-00（列舉與慣例）、SPEC-M4A（open_trace / record_step 介面）。
> 本文件定義「一個決策週期從生到死」的骨架；分派邏輯見 SPEC-O2，對外介面見 SPEC-O3。

## 1. 週期定義

**決策週期（cycle）**＝一次「觸發 → 編排 → 匯總 → 推送」的完整流程，對應恰好一個 `trace_id`。

週期的兩種來源：

| 來源 | 進入點 | 分派模式（SPEC-O2） |
|---|---|---|
| 規則觸發批次 | 規則引擎（P5）每 tick 產出的 `TriggeredRule[]` | 靜態分派表 |
| 事件注入 | D4 監聽器收到 `live_incidents.json` 事件 → A1 分類 | A2 LLM 規劃器 |

同一 tick 同時存在兩種來源時，**合併為一個週期**（複合事件，見 SPEC-O2 §4）。

## 2. 週期生命週期（七階段）

```
1. OPEN      生成 trace_id（TR-YYYYMMDD-HHMM-serial，行程內計數器）
             open_trace(trace_id, triggered_by[])
             triggered_by = 批次規則 ∪ 事件命中條款（例 ["§1-A","§2","§6"]）

2. FLAGS     處理 §6：P3 漫遊率 ≥ 0.30 → GlobalState.multilingual = true
             → record_step(A2, action="SET_FLAG")；§6 不產生分派

3. PLAN      建構 DispatchPlan（SPEC-O2：靜態表 / LLM 規劃器 / 混合）

4. EXECUTE   逐 Phase 執行（平行 join / 串聯傳遞），每任務前記 DISPATCH

5. SUMMARY   record_step(A2, action="CYCLE_SUMMARY",
             subject_segment_ids=本週期全部涉及路段, duration_ms=總耗時)

6. EXPLAIN   generate_report_explanation(trace_id)（M4B；失敗降級見 SPEC-O2 §6）

7. PUSH      組裝 DecisionResult（SPEC-O3）→ REST 回傳 + WebSocket 推播
             更新 GlobalState.active_incidents
```

## 3. GlobalState

```
GlobalState {
  multilingual:      bool                        // §6 flag；預設 false。
                     // 生效範圍：設定後對「本週期及後續週期」的 C4 呼叫皆生效，
                     // 直到漫遊率連續一個 tick 低於 0.30 時重置為 false。
  active_incidents:  map<event_id, IncidentRecord> // 進行中 §2/§5 事件
                     // 寫入：週期 PUSH 階段；移除：收到恢復訊號（Partial_Open 等）
  cycle_counter:     int                         // trace_id 流水號（行程內）
}
```

單一行程假設下 GlobalState 為行程內記憶體物件（對齊隊友「Python 記憶體」實作）；不做跨行程共享。

## 4. 併發約束：週期 FIFO 排隊

同一時間僅一個週期執行。前一週期未完成（未到 PUSH）又收到新觸發 → 新週期排入 FIFO 佇列。

理由：兩週期並行會同時讀寫 GlobalState 與搶佔 LLM/工具資源，引入不可重現的競態；資料節奏為 15 分鐘一批，排隊無實際延遲代價。

例外：**W1 What-if 問答不是週期**（不寫 trace、不進佇列），可與進行中週期並行回答——W1 只讀狀態不改狀態。

## 5. 與模組四（A4）的呼叫時序契約

| 時機 | 呼叫 | 責任方 |
|---|---|---|
| OPEN | `open_trace(trace_id, triggered_by[])` | A2 |
| FLAGS | `record_step(agent="A2", action="SET_FLAG")` | A2 |
| 每任務分派前 | `record_step(agent="A2", action="DISPATCH")` → 取得 dispatch_seq | A2 |
| LLM 規劃器產出計畫時 | `record_step(agent="A2", action="PLAN", input={工具序列})` | A2 |
| 工具/模組執行中 | `record_step(agent=<ActorCode>, parent_seq=dispatch_seq, ...)` | A2（[2026-07-28更正] 原寫「各執行模組」易誤導——R1-R5／A3／C1-C4 是純函式（`routing.py`／`reporting.py`），完全不知道追蹤機制存在，不 import M4A、不自己呼叫 `record_step`。實際是 A2 呼叫完這些模組拿到回傳值（`RoutePlanResult`／`EteEstimate`等）後，代為呼叫 `record_step`，`agent` 欄位填對應的 `ActorCode` 只是標示「這步驟的執行者是誰」，不代表呼叫者是誰） |
| 任務逾時 | `record_step(agent="A2", action="AGENT_TIMEOUT")` | A2 |
| SUMMARY | `record_step(agent="A2", action="CYCLE_SUMMARY")` | A2 |
| EXPLAIN | `generate_report_explanation(trace_id)` | A2 |
| 回溯追問（隨時） | `answer_trace_query(trace_id, question)` | A2（經 SPEC-O3 路由） |

**錯誤處理分界**：M4A 拋出的 `ValueError`（驗證失敗）不捕捉——代表程式缺陷，fail fast。M4B 的 LLM 生成失敗依 M4B 契約降級。

**What-if 明確不在此表**：W1 不呼叫 open_trace / record_step（SPEC-00 §4 慣例）。

## 6. 保留 action 值

```
SET_FLAG        // §6 flag 設定
PLAN            // LLM 規劃器產出的工具序列（僅事件注入流程）
DISPATCH        // 分派決策
AGENT_TIMEOUT   // 任務逾時補記
CYCLE_SUMMARY   // 週期匯總
```

## 7. 驗收測試（決定性）

| # | 情境 | 預期 |
|---|---|---|
| 1 | 單規則批次 [§1-A] | 恰一次 open_trace(["§1-A"])；SUMMARY 存在；trace 序號連續 |
| 2 | trace_id 流水號 | 同分鐘內兩週期 → serial 遞增不重複 |
| 3 | §6 flag 生效與重置 | 含 §6 批次後 multilingual=true；漫遊率 < 0.30 的下一 tick 後重置 false |
| 4 | FIFO 排隊 | 週期執行中注入新事件 → 新週期的 open_trace 時間戳晚於前週期 CYCLE_SUMMARY |
| 5 | What-if 不開 trace | W1 問答期間 record_step 呼叫次數為 0（mock 驗證） |
| 6 | active_incidents 生命週期 | §2 事件 PUSH 後存在於 map；注入恢復訊號後移除 |
