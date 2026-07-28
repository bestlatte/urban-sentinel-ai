# SPEC-O3 Orchestrator：對外介面與路由 — v1

> 依賴：SPEC-00、O1、O2。本文件是 Orchestrator 與「規則引擎（上游）、前端（下游）、W1（旁路）」的邊界契約。

## 1. 介面總覽

```
handle_trigger_batch(batch: TriggeredRule[]) -> DecisionResult   # 規則引擎呼叫
handle_incident(event: IncidentEvent)        -> DecisionResult   # D4 監聽器呼叫（REST POST /api/incidents/evaluate 之後端）
handle_user_query(question, current_trace_id) -> AnswerText      # 前端對話（REST POST /api/what-if）
get_global_state() / reset()                                     # 測試與 demo 重播輔助
```

> **[2026-07-28 總架構師補註]** 原文分別寫 `/api/inject`、`/api/chat`，都不在 `00-tech-stack.md` §4 固定的 4 個端點內（該文件明訂「API 表面固定，不得擴充」）。已改成對應的固定端點：事件注入走 `POST /api/incidents/evaluate`，使用者對話（含 What-if 與回溯追問）走 `POST /api/what-if`——這跟 `W1-whatif-agent/design.md` 已經修正的入口一致，這裡是回頭把 SPEC-O3 本體也改掉，避免兩份文件各寫各的端點名稱。

同 tick 的 batch 與 incident 由整合層合併後以複合週期處理（SPEC-O2 §4）；本層介面各自可獨立呼叫。

## 2. 輸入結構

```
TriggeredRule { rule: "§\d+(-[A-Za-z])?", segment_id: string|null,
                payload: object, emitted_at: string }

IncidentEvent  // 直接沿用 live_incidents.json 單筆結構
{ event_id, type, location, affected_segment, status, severity, timestamp, ... }
```

前置驗證：batch 空陣列拋 ValueError；event_id / affected_segment 缺漏拋 ValueError（fail fast）。

## 3. DecisionResult（推送與回傳的統一輸出）

> **[2026-07-28 總架構師補註] 欄位名改以 `m5-api-orchestrator-dashboard/design.md` 為準**：`src/models.py` 是 `01-module-boundaries.md` 分工決議下「全專案唯一定義處」，`DecisionResult` 的實際欄位名由 M5 的機器契約（`contracts/module_exchange_contract.json`）決定，SPEC-O3 只負責描述編排流程與資料從哪裡來，不重新發明欄位名。原本這裡的 `reports.advisory`／`reports.sms` 跟 M5 design.md 的 `control_center_report`／`notifications`（扁平欄位，不包在 `reports` 底下）對不起來，已改用 M5 的命名；`routes.excluded`／`routes.findings` 用於 `SPEC-M4A` 的決策軌跡記錄，維持不變。
> **[2026-07-28 二次更正]** 下方原補了一個 `routes.candidate_evaluations` 欄位，是我自己猜錯的名字——`m5-api-orchestrator-dashboard/requirements.md` R4.2、R7.6 兩處明確使用 `candidates`（不是 `candidate_evaluations`），這才是 M5 實際採用的欄位名，已改正。

```
DecisionResult {
  trace_id:       string
  triggered_by:   string[]
  level:          "A" | "B" | null          // P5 判定
  incident:       object | null             // 事件摘要（event_id、位置、條款）
  routes: {
    primary:               {segment_id, name} | null
    secondary:             {segment_id, name} | null
    excluded:              [{segment_id, reason_code, reason_detail}]
    findings:              [{finding_code, segment_ids, evidence}]   // 含 SATURATED_BUT_RETAINED
    candidates:            [object]           // 完整候選評估清單（M2-C 原樣輸出，含合格與不合格）
  } | null
  ete:                     {minutes: int, recovery_at: "YYYY-MM-DD HH:MM", formula: string} | null
  control_center_report:   string | null      // C1 建議書全文（生成失敗時 null + degraded 標示）；
                                                // C2 號誌配時建議、C3 跨系統聯動建議併入同一段全文，
                                                // 不拆成獨立結構化欄位
  notifications:           {zh: string, en?: string, ja?: string, ko?: string} | null  // C4
  degraded:                string[]           // 降級註記（如 ["C1_FAILED","P5_TIMEOUT"]）
  duration_ms:             int
  is_simulated:            bool               // [2026-07-28更正] 原寫死字面值 true，但 signaling_crowd_density.csv
                                                // 已是主辦方提供的真實資料（provenance="provided"），不再全部模擬。
                                                // 改為依本次決策實際引用的資料來源計算：只要有任一 provenance="demo"
                                                // 的欄位被使用，才為 true；全部 provided/derived 則為 false。
}
```

（原本 `signal_plan`／`coordination` 曾是獨立 `object`，後併入單一 `control_center_report` 全文：C2/C3 的內容本來就是 LLM 依 C1 事實生成的文字建議，若要在 orchestrator 層把它們拆回結構化物件，等於要對 LLM 生成的自然語言重新做結構化解析，違反「LLM 只表達事實、不產生事實」原則。`degraded` 陣列若含 `"C1_FAILED"` 代表整份建議書（含原本 C2/C3 部分）生成失敗。）

**雙通道保底**：REST POST 的同步 response 與 WebSocket 推播內容為同一份 DecisionResult；前端以推播為主、POST 回傳為保底，且不重算任何欄位。

## 4. 使用者輸入路由（確定性，零 LLM）

```
1. question 含前瞻假設詞（「如果」「假設」「若」「會怎樣」「怎麼辦」任一）
   → 轉發 W1（What-if）：LLM 解析參數 → Python 工具重算 → LLM 敘述
     不寫 trace（SPEC-00 慣例）；W2 維護對話狀態；可與進行中週期並行
     → 回應：message_type="whatif.evaluated.v1"，payload=WhatIfResult
2. 否則若 current_trace_id 非 null
   → answer_trace_query(current_trace_id, question)（M4B 回溯追問）
     → 回應：message_type="trace.answered.v1"，payload=TraceAnswer{trace_id, answer_text}
3. 否則
   → 固定文字：「目前無進行中的決策週期可查詢。若要詢問假設情境，請以『如果…』開頭。」
     → 回應：message_type="trace.answered.v1"，payload=TraceAnswer{trace_id: null, answer_text: 固定文字}
```

優先序約定：前瞻詞優先於回溯（問題同時含假設詞與路段名 → 走 W1）。寫入測試固定。

> **[2026-07-28 總架構師補註]** 三種分支共用同一個端點 `POST /api/what-if`（固定 API 表面不擴充），但回應形狀不同——分支1回傳完整重算結果 `WhatIfResult`；分支2、3只是一段文字，不勉強塞進 `WhatIfResult` 的 `route_plan`/`ete`/`rule_hits` 等欄位，改用新增的輕量型別 `TraceAnswer`，靠 `message_type` 分派（跟 F6 的 `chat.*.v1`、本文件 §5 的 `decision.*.v1` 是同一套機制）。詳見 `m5-api-orchestrator-dashboard/requirements.md` R2.5/R2.5a。

## 5. WebSocket 事件型別

> **[2026-07-28 總架構師補註]** 原本是裸字串（`"alert"` 等），沒有套用 `00-tech-stack.md` §7「Message Type `<domain>.<action>.v<version>`」的命名慣例，也沒有包 `02-data-contract.md` §7 的 Message Envelope（`message_type`/`payload` 等固定欄位）。`/ws` 是全專案唯一連線，F1-F7 共用，訊息格式要跟 F6 已經對齊的 `chat.*.v1` 風格一致，前端才能用同一套 `message_type` 分派邏輯處理所有模組的推播。已改用 `decision.<action>.v1` 命名，實際內容放在 Envelope 的 `payload` 裡。

```
decision.alert.v1           // P5 預警（B/A 級轉換）→ 前端 F2 自動彈窗
decision.cycle_start.v1     // 週期開始（trace_id + triggered_by）→ Agent 活動面板
decision.task_update.v1     // 任務 DISPATCH / 完成 / 逾時 → 活動面板即時狀態
decision.completed.v1       // 完整 DecisionResult → F4 地圖 / F5 卡片 / F7 決策依據
                             // （[2026-07-28更正] 原寫 decision.result.v1，跟 m5-api-orchestrator-dashboard/design.md
                             //  既有命名重複定義同一個推播事件，已統一改用 M5 的 decision.completed.v1）
```

## 6. 驗收測試

| # | 情境 | 預期 |
|---|---|---|
| 1 | 路由前瞻優先 | 「如果封閉市民大道會怎樣」+ trace 非 null → W1 被呼叫、answer_trace_query 不被呼叫 |
| 2 | 路由回溯 | 「為什麼不走延吉街」+ trace 非 null → answer_trace_query 被呼叫 |
| 3 | 路由無週期 | trace = null → 回固定引導文字，零下游呼叫 |
| 4 | 雙通道一致 | POST 回傳與 WS 推播的 DecisionResult 深度相等 |
| 5 | 降級標示 | C1 mock 失敗 → control_center_report=null 且 degraded 含 "C1_FAILED" |
| 6 | ACC_001 黃金值 | DecisionResult.routes 與 ete 符合 SPEC-00 §5（主 004 / 次 005 / ETE 90 分 / 恢復 23:40） |
| 7 | 多語欄位 | multilingual=true → notifications 至少含 zh/en；false → 僅 zh |
| 8 | is_simulated | [2026-07-28更正] 引用真實 `signaling_crowd_density.csv`（provenance="provided"）的決策 → `false`；若有欄位仍為 provenance="demo"（例如缺值補位）才 → `true`，不恆為 true |
