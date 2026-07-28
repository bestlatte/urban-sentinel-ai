# Requirements Document — M5 決策編排、API 與 Dashboard

## Introduction

本 spec 定義模組 5（M5）的需求範圍：**決策編排（A2）、事件分類（A1）、決策留痕（A4）、固定 API 表面、WebSocket 推播與 Dashboard 前端（F1–F7、FWS）**，契約模組代碼為 `api_orchestrator` 與 `dashboard`。

M5 是整合層。它**只負責編排與呈現**：任何規則判定（A/B 級、SOP 命中）、路網篩選（主／次路線、排除理由）、ETE 與報告文字，全部呼叫 M1／M2／M3／M4 取得，M5 內不得存在第二份實作。

M5 同時擁有 `src/models.py` 與 `contracts/module_exchange_contract.json`，是全專案共用型別的唯一定義處，因此本 spec 的第一組需求會擋住其他四位成員的開發進度。

## 前提（引用來源，本文件不重述）

以下內容已由 steering 與機器契約定義，本文件與 design.md **一律以引用取代重述**：

| 主題 | 權威來源 |
|---|---|
| Message Envelope 欄位、錯誤碼、provenance、留痕原則 | `.kiro/steering/02-data-contract.md` 第 7 節 |
| 單位換算、正規化規則（Roaming÷100、Growth_Rate 不轉換等） | `.kiro/steering/02-data-contract.md` 第 2 節 |
| Join 與 as-of 時間對齊規則 | `.kiro/steering/02-data-contract.md` 第 3 節 |
| A/B 級門檻、SOP 門檻數值、severity 列舉 | `.kiro/steering/02-data-contract.md` 第 4 節 |
| 路網篩選與飽和兩段式規則 | `.kiro/steering/02-data-contract.md` 第 5 節 |
| ETE 公式與三筆事件固定驗收值 | `.kiro/steering/02-data-contract.md` 第 6 節 |
| 前端顯示規則（色彩、Demo 標示） | `.kiro/steering/02-data-contract.md` 第 8 節 |
| 五個 canonical JSON 的來源與筆數 | `.kiro/steering/02-data-contract.md` 第 1 節 |
| 技術棧、固定 API 表面、環境變數、保底模式 | `.kiro/steering/00-tech-stack.md` 第 1、4、5、6 節 |
| 模組所有權、決策職責三層、固定資料流向 | `.kiro/steering/01-module-boundaries.md` 第 1–4 節 |
| 所有型別的欄位定義與列舉值 | `contracts/module_exchange_contract.json` |

需求編號 R1–R9 引用 `五人團隊分工與Spec開發建議書.md` 第 9.1 節。

## 檔案所有權

**可寫（M5 擁有）**：`main.py`、`src/models.py`、`src/orchestrator.py`、`src/ws_manager.py`、`frontend/**`、`contracts/module_exchange_contract.json`

**唯讀（其他模組擁有）**：`src/loaders.py`、`src/rules.py`（M1）、`src/routing.py`、`data/display_geometry.json`（M2）、`src/agent.py`、`src/bedrock_service.py`、`prompts/**`（M3）、`src/reporting.py`（M4）、`data/**`

## Glossary

- **M5_Models**：`src/models.py`，全專案 Pydantic 型別與 Envelope 建構的唯一定義處。
- **M5_Api**：`main.py` 提供的 FastAPI 應用，含四個 REST 端點、`/ws` 與 `frontend/` 靜態掛載。
- **A1_Classifier**：`src/orchestrator.py` 內的決定性事件分類器，依事件型別與欄位決定主因 SOP 與是否需要改道。
- **M5_Orchestrator**：`src/orchestrator.py` 內的 A2 編排器，依序呼叫 M1／M2／M3／M4 並組裝 `DecisionResult`。
- **M5_WhatIf**：`src/orchestrator.py` 內的 What-if 編排流程，產生 `WhatIfResult`。
- **A4_TraceLogger**：`src/orchestrator.py` 內的決策留痕元件，以記憶體字典保存整份 `DecisionResult`。
- **M5_WsManager**：`src/ws_manager.py` 的 WebSocket 連線管理與廣播元件。
- **M5_Dashboard**：`frontend/**` 的單頁 Dashboard 前端。
- **M5_MockLayer**：開發初期在 M1–M4 尚未完成時，供四個端點與 `/ws` 回傳符合契約假資料的替身實作。
- **契約型別**：`contracts/module_exchange_contract.json` 的 `$defs` 所定義的型別。
- **事實欄位**：`.kiro/steering/01-module-boundaries.md` 第 3 節列出、禁止由 LLM 產生或修改的欄位集合。
- **主因 SOP**：造成該事件被判定的首要 SOP 條款；其餘同時成立者為並行命中。

---

## Requirements

### Requirement 1：共用型別的單一定義處

**對應**：全模組共用基礎（支撐 R1–R9）　**架構節點**：API／整合層

**User Story:** 作為架構整合者，我要 `src/models.py` 成為所有跨模組型別的唯一定義處，讓其他四位成員可以並行開發而不會產生互不相容的資料格式。

#### Acceptance Criteria

1. THE M5_Models SHALL 定義下列契約型別的 Pydantic Model：`DataProvenance`、`ErrorDetail`、`TrafficSample`、`CrowdSample`、`DisplayPoint`、`RoadSegment`、`Incident`、`SopClause`、`NormalizedDataBundle`、`EvidenceRef`、`RuleHit`、`SensingResult`、`RouteRequest`、`RouteCandidate`、`RoutePlan`、`EteEstimate`、`SopEvidence`、`BedrockAdvisory`、`ScenarioOverrides`、`WhatIfRequest`、`WhatIfResult`、`TraceAnswer`（[2026-07-28新增] `POST /api/what-if` 回溯追問分支用，見 R2.5a）、`Notification`、`DecisionResult`、`DashboardPayload`，以及列舉型別 `ModuleName`、`MessageType`、`IncidentSeverity`。
2. THE M5_Models SHALL 使每個 Model 的欄位名稱、必填性與列舉值與 `contracts/module_exchange_contract.json` 對應 `$defs` 完全一致。
3. THE M5_Models SHALL 提供單一的 Envelope 建構函式，由呼叫方傳入 `message_type`、`source_module`、`target_module`、`status`、`payload`、`provenance`、`warnings`、`errors`，並由該函式產生 `schema_version`、`message_id` 與 `generated_at`。
4. WHEN 一次事件評估或一次 What-if 流程開始，THE M5_Orchestrator SHALL 產生一個 `correlation_id`，並讓該流程中所有 REST 回應與 WebSocket 推播的 Envelope 使用同一個 `correlation_id`。
5. THE M5_Models SHALL 以 `Asia/Taipei`（`+08:00`）時區輸出所有時間欄位。
6. IF 任何模組需要新增或變更共用欄位，THEN THE M5_Models SHALL 在 `contracts/module_exchange_contract.json` 先完成對應變更後才更新，且變更請求須註明 Requirement ID 與受影響模組。
7. WHERE 其他模組使用共用型別，THE M5_Models SHALL 作為其唯一 import 來源，其他模組不得自行定義同名型別。

---

### Requirement 2：固定 API 表面與單一 Server

**對應**：R8、R9　**架構節點**：API Gateway

**User Story:** 作為前端與其他模組的整合者，我要一組固定不變的 API 表面，讓前端與後端可以獨立開發並在同一個 Server 上完成 Demo。

#### Acceptance Criteria

1. THE M5_Api SHALL 只提供 `GET /api/dashboard`、`POST /api/incidents/evaluate`、`POST /api/what-if`、`GET /api/health` 四個 REST 端點與 `WS /ws` 一個 WebSocket 端點。
2. THE M5_Api SHALL 在同一個 FastAPI 應用中掛載 `frontend/` 靜態檔，使前端與 API 由同一個 Uvicorn 行程提供。
3. WHEN `GET /api/dashboard` 被呼叫，THE M5_Api SHALL 回傳 `message_type` 為 `dashboard.updated.v1`、`payload` 為 `DashboardPayload` 的 Envelope。
4. WHEN `POST /api/incidents/evaluate` 帶合法 `event_id` 被呼叫，THE M5_Api SHALL 回傳 `message_type` 為 `decision.completed.v1`、`payload` 為 `DecisionResult` 的 Envelope。
5. WHEN `POST /api/what-if` 帶合法 `WhatIfRequest` 被呼叫且問題屬於前瞻假設（含「如果」「假設」「若」等詞，`SPEC-O3` §4 路由規則），THE M5_Api SHALL 回傳 `message_type` 為 `whatif.evaluated.v1`、`payload` 為 `WhatIfResult` 的 Envelope。
5a. [2026-07-28新增] WHEN `POST /api/what-if` 帶合法請求但問題屬於回溯追問（`current_trace_id` 非 null 且非前瞻假設詞）或無進行中週期，THE M5_Api SHALL 回傳 `message_type` 為 `trace.answered.v1`、`payload` 為 `TraceAnswer { trace_id: string | null, answer_text: string }` 的 Envelope，不勉強套用 `WhatIfResult` 的形狀（回溯追問只是一段文字，沒有 `route_plan`/`ete`/`rule_hits` 等重算欄位可填）。此分支對應 `SPEC-O3` §4 的第 2、3 種路由結果。
6. THE M5_Api SHALL 使 `GET /api/health` 回傳不使用 Envelope 的簡單健康狀態物件，內容包含服務存活標記與 `USE_BEDROCK` 目前設定值。
7. IF `POST /api/incidents/evaluate` 收到的 `event_id` 不存在於 M1 提供的 `NormalizedDataBundle.incidents`，THEN THE M5_Api SHALL 回傳 `status` 為 `error`、`errors[0].code` 為 `DATA_NOT_FOUND` 的 Envelope。
8. IF 下游模組回傳失敗但已取得可呈現的部分結果，THEN THE M5_Api SHALL 回傳 `status` 為 `partial` 的 Envelope，並在 `warnings` 記錄失敗的模組名稱與原因。
9. IF 請求本體未通過 Pydantic 驗證，THEN THE M5_Api SHALL 回傳 `status` 為 `error`、`errors[0].code` 為 `VALIDATION_ERROR` 的 Envelope，並在 `errors[0].field` 標明失敗欄位。
10. THE M5_Api SHALL 使所有改變系統狀態的操作以 REST 同步回傳完整結果，不依賴 WebSocket 傳遞主要結果。

---

### Requirement 3：A1 事件分類（決定性，不使用 LLM）

**對應**：命題模組 2、R3　**架構節點**：A1 事件分類器

**User Story:** 作為指揮中心系統，我要事件在進入編排前被決定性地分類，讓每次 Demo 對同一筆事件都得到相同的主因 SOP 與相同的處理路徑。

#### Acceptance Criteria

1. THE A1_Classifier SHALL 以事件的 `type`、`severity`、`status`、`affected_segment` 與 `affected_road` 欄位判定主因 SOP 與 `requires_rerouting` 布林值，不呼叫任何語言模型。
2. WHEN 事件 `type` 為 `Road_Collapse_Accident`，THE A1_Classifier SHALL 判定主因 SOP 為 `SOP-2` 並設定 `requires_rerouting` 為 true。
3. WHEN 事件 `type` 為 `Crowd_Surge_Injury`，THE A1_Classifier SHALL 判定主因 SOP 為 `SOP-3`。
4. WHERE 事件同時具備 `affected_road`，THE A1_Classifier SHALL 以 `affected_road` 作為受影響路段來源，優先於由 `affected_segment` 推導的結果。
5. WHEN 事件 `type` 為 `Power_Failure`，THE A1_Classifier SHALL 判定主因 SOP 為 `SOP-5`，並設定 `requires_rerouting` 為 false。
6. IF 事件 `type` 為 `Power_Failure`，THEN THE A1_Classifier SHALL 使主因 SOP 不為 `SOP-2` 且不為 `SOP-1`。
7. WHEN M1 回傳的 `SensingResult.rule_hits` 含有主因 SOP 以外的其他條款，THE M5_Orchestrator SHALL 將它們標記為並行命中並全部保留於 `DecisionResult.rule_hits`，且不改寫主因 SOP。
8. IF 事件 `type` 不在 A1_Classifier 的對照表中，THEN THE A1_Classifier SHALL 設定 `requires_rerouting` 為 false，並在 Envelope `warnings` 記錄未知事件型別，且流程繼續執行。
9. THE A1_Classifier SHALL 對同一輸入事件的重複呼叫回傳相同的分類結果。

---

### Requirement 4：A2 編排與 DecisionResult 組裝

**對應**：命題模組 2、4、5；R4、R5、R6　**架構節點**：A2 編排

**User Story:** 作為值班指揮官，我要按下事件評估後在單一回應中拿到級別、路線、ETE、建議書與簡訊，讓我不需要在多個系統之間拼湊資訊。

#### Acceptance Criteria

1. WHEN 一次事件評估開始，THE M5_Orchestrator SHALL 依序取得 M1 的 `NormalizedDataBundle` 與 `SensingResult`，再依 A1_Classifier 結果取得 M2 的 `RoutePlan`，再取得 M4 的 `EteEstimate`、交控建議書與 `Notification`，最後取得 M3 的 `BedrockAdvisory`。
2. THE M5_Orchestrator SHALL 透過呼叫 M1、M2、M4 取得 `traffic_level`、`rule_hits`、`primary_route`、`secondary_route`、`candidates`、`ete_minutes` 與 `estimated_recovery_at`，且不在 M5 內重新計算上述任何欄位。
3. WHEN A1_Classifier 判定 `requires_rerouting` 為 false，THE M5_Orchestrator SHALL 設定 `DecisionResult.route_plan` 為 null 並繼續完成 ETE、建議書、簡訊與 advisory 的取得。
4. WHEN 任一站點的 `roaming_user_pct` 達到 `.kiro/steering/02-data-contract.md` 第 4 節 SOP-6 門檻，THE M5_Orchestrator SHALL 觸發 M4 產生多語 `Notification`。
5. IF 沒有任何站點的 `roaming_user_pct` 達到 SOP-6 門檻，THEN THE M5_Orchestrator SHALL 只產生 `zh-TW` 與 `en` 的 `Notification`。
6. THE M5_Orchestrator SHALL 在組裝 `DecisionResult` 時，以 Python 端取得的事實欄位為最終值，並忽略 `BedrockAdvisory` 中與事實欄位同名的任何內容。
7. THE M5_Orchestrator SHALL 設定 `BedrockAdvisory.fact_source` 為 `python_decision_facts`，並確認 `sop_evidence` 至少含一筆。
8. IF `BedrockAdvisory` 缺少 `sop_evidence` 或其敘述未包含 Python 提供的事實欄位值，THEN THE M5_Orchestrator SHALL 改用 M4 的模板文字作為 `DecisionResult.control_center_report` 內容（[2026-07-28更正] 原寫「`DecisionResult.advisory` 與 `control_center_report`」，`DecisionResult` 上並沒有 `advisory` 這個欄位，已移除誤植），並在 `warnings` 記錄改用模板的原因。
9. THE M5_Orchestrator SHALL 量測整次編排耗時並寫入 `DecisionResult.duration_ms`，且依 `duration_ms` 是否不大於 60000 設定 `within_60_second_sla`。
10. IF 任一下游模組呼叫超過其逾時上限，THEN THE M5_Orchestrator SHALL 中止該次呼叫、以 `status` 為 `partial` 回傳已取得的結果、在 `errors` 加入 `code` 為 `TIMEOUT` 的項目，並在 `warnings` 記錄超時模組。
11. THE M5_Orchestrator SHALL 使 `data/live_incidents.json` 三筆事件的 `rule_hits` 主因、`primary_route`、`secondary_route`、排除理由、`ete_minutes` 與 `estimated_recovery_at` 與 `.kiro/steering/02-data-contract.md` 第 6 節固定驗收值表一致。
12. THE M5_Orchestrator SHALL 對同一 `event_id` 的重複評估回傳除 `decision_id`、`message_id`、`generated_at`、`completed_at` 與 `duration_ms` 以外皆相同的 `DecisionResult`。

---

### Requirement 5：A4 決策留痕

**對應**：命題模組 4、R5、R8　**架構節點**：A4 Decision Trace Logger

**User Story:** 作為稽核與展示需求方，我要每次正式決策都留下完整可回溯的紀錄，讓評審能看到決策依據而不只是結論。

#### Acceptance Criteria

1. WHEN 一次事件評估完成，THE A4_TraceLogger SHALL 將整份 `DecisionResult` 寫入決策軌跡，內容包含交控建議書全文與所有 `Notification` 的 `content` 全文。
2. THE A4_TraceLogger SHALL 使每個 `event_id` 在決策軌跡中僅對應一筆紀錄。
3. WHEN 同一 `event_id` 被重新評估，THE A4_TraceLogger SHALL 以新的 `DecisionResult` 覆寫既有紀錄。
4. THE A4_TraceLogger SHALL 保存該次編排的 A2 工具呼叫順序與每筆 `RuleHit` 引用的 `clause_id`，供決策依據面板顯示。
5. IF 決策留痕寫入失敗，THEN THE A4_TraceLogger SHALL 在 Envelope `warnings` 記錄寫入失敗，且 REST 回應仍回傳完整 `DecisionResult`。
6. WHILE 一次 What-if 流程執行中，THE A4_TraceLogger SHALL 不寫入任何決策軌跡紀錄。
7. THE A4_TraceLogger SHALL 以 Python 記憶體結構保存決策軌跡，使核心流程不依賴外部資料庫。

---

### Requirement 6：WebSocket 主動推播

**對應**：命題模組 1、R9　**架構節點**：FWS

**User Story:** 作為值班指揮官，我要異常與決策結果自動出現在畫面上，讓我不必反覆手動查詢就能掌握狀況。

#### Acceptance Criteria

1. WHEN 一個前端連線至 `/ws`，THE M5_WsManager SHALL 將該連線加入使用中連線集合。
2. WHEN 一個連線關閉或推播該連線時發生傳送錯誤，THE M5_WsManager SHALL 將該連線自使用中連線集合移除，並繼續對其餘連線推播。
3. THE M5_WsManager SHALL 支援推播 `rules.evaluated.v1`、`dashboard.updated.v1`、`decision.completed.v1`、`whatif.evaluated.v1` 四種 `message_type`。
4. THE M5_WsManager SHALL 使推播訊息使用與對應 REST 回應相同的 Envelope 格式與相同的 `payload` 內容。
5. THE M5_WsManager SHALL 只處理由伺服器發往用戶端的訊息，並忽略用戶端經 `/ws` 送來的任何訊息內容。
6. IF `/ws` 連線中斷，THEN THE M5_Dashboard SHALL 自動嘗試重新連線，並在未連線期間改以輪詢 `GET /api/dashboard` 更新畫面。
7. THE M5_Dashboard SHALL 使 KPI、地圖、決策依據、建議書與簡訊在僅使用 REST 回應的情況下仍完整顯示。
8. IF 目前沒有任何使用中連線，THEN THE M5_WsManager SHALL 略過推播並使 REST 流程正常完成。

---

### Requirement 7：Dashboard 呈現

**對應**：命題模組 1、2、4、5；R1、R2、R8　**架構節點**：F1–F7

**User Story:** 作為值班指揮官，我要在單一頁面看到現況、事件、決策依據與對外文稿，讓我能在一個畫面內完成判斷與說明。

#### Acceptance Criteria

1. THE M5_Dashboard SHALL 在單一頁面提供 KPI 卡片區、SVG 路網拓樸圖、時序圖表區、事件注入面板、決策依據面板、建議書與簡訊卡片區，以及 What-if 對話框。
2. THE M5_Dashboard SHALL 以 `DashboardPayload.kpis` 的欄位值直接呈現 KPI 卡片，不在 JavaScript 內計算任何 KPI 數值。
3. THE M5_Dashboard SHALL 使用 Chart.js 繪製車流與人流時序圖，並在圖上標示 `.kiro/steering/02-data-contract.md` 第 4 節定義的門檻線。
4. THE M5_Dashboard SHALL 以 `display_geometry.json` 的 `display_points` 決定 SVG 節點位置，並依 `.kiro/steering/02-data-contract.md` 第 8 節的色彩規則繪製級別、主／次路線與封閉路段。
5. WHEN 使用者在事件注入面板選定一筆 `available_incidents` 中的事件並送出，THE M5_Dashboard SHALL 呼叫 `POST /api/incidents/evaluate` 並以回應內容更新畫面。
6. THE M5_Dashboard SHALL 在決策依據面板顯示每筆 `RuleHit` 的 `clause_id` 與條款內容，以及 `RoutePlan.candidates` 中每個候選的排除或保留理由。
7. THE M5_Dashboard SHALL 在建議書與簡訊卡片區顯示 `control_center_report` 全文與每筆 `Notification` 的語言、通道與 `content` 全文。
8. WHERE `kpis.crowd_data_classification` 為 `demo`，THE M5_Dashboard SHALL 在人流卡片與人流圖表標示「Simulated / Demo Scenario」。
9. IF `kpis.crowd_data_classification` 為 `unavailable`，THEN THE M5_Dashboard SHALL 在人流卡片顯示「資料未提供」，且不顯示任何推測數值。
10. WHILE 一次評估或 What-if 請求尚未回應，THE M5_Dashboard SHALL 顯示運算中動畫，且該動畫的單次循環時間不超過 2 秒。
11. THE M5_Dashboard SHALL 不在 JavaScript 內判定 `traffic_level`、篩選路線候選或計算 `ete_minutes`。
12. THE M5_Dashboard SHALL 支援自 `frontend/vendor/` 載入 Chart.js，使頁面在無外部網路的環境下完整顯示。

---

### Requirement 8：What-if 編排

**對應**：命題模組 3、R7　**架構節點**：A2 編排（What-if 分支）

**User Story:** 作為評審，我要現場提出假設情境並看到重新計算後的結果，讓我確認系統是真的在算而不是在背答案。

> **[2026-07-28 總架構師補註]** 本節只涵蓋 `POST /api/what-if` 收到**前瞻假設問題**時的分支（`SPEC-O3` §4 路由規則第1種）。同一端點收到**回溯追問**或**無進行中週期**時走不同分支，回應是 `TraceAnswer` 而非 `WhatIfResult`（見 R2.5a），不受本節 Acceptance Criteria 約束——那兩種分支呼叫的是 `answer_trace_query()`（M4B）或固定文字，不經過 M1/M2/M4 重算。

#### Acceptance Criteria

1. THE M5_WhatIf SHALL 使 `WhatIfResult.simulation_only` 固定為 true。
2. WHEN 一次 What-if 請求開始，THE M5_WhatIf SHALL 先呼叫 M3 將自然語言問句解析為 `ScenarioOverrides`，再呼叫 M1／M2／M4 以覆寫後資料重算，最後呼叫 M3 產生敘述文字。
3. THE M5_WhatIf SHALL 以 M1／M2／M4 的重算輸出填入 `WhatIfResult` 的 `rule_hits`、`route_plan`、`ete` 與 `sop_evidence`，且不以 M3 的輸出填入上述欄位。
4. THE M5_WhatIf SHALL 在 `WhatIfResult.differences_from_base` 記錄與 `base_decision_id` 對應基準結果之間的差異項目。
5. WHEN `base_decision_id` 未提供，THE M5_WhatIf SHALL 以 `base_as_of` 時點的現況作為比較基準。
6. THE M5_WhatIf SHALL 將 `ScenarioOverrides` 套用於 `NormalizedDataBundle` 的記憶體副本，使 `data/` 下的檔案內容與決策軌跡皆不變更。
7. IF `WhatIfRequest.scenario_overrides` 未提供任何覆寫項目，THEN THE M5_Api SHALL 回傳 `status` 為 `error`、`errors[0].code` 為 `VALIDATION_ERROR` 的 Envelope。
8. IF M3 解析問句失敗，THEN THE M5_WhatIf SHALL 回傳 `status` 為 `error`、`errors[0].code` 為 `MODEL_INVOCATION_FAILED` 的 Envelope，並在 `warnings` 說明可改以明確覆寫參數重試。
9. WHEN 一次 What-if 完成，THE M5_Orchestrator SHALL 使既有 `DecisionResult` 與決策軌跡內容保持不變。

---

### Requirement 9：保底模式與可展示性

**對應**：R1–R9 全部　**架構節點**：API／A2／FE

**User Story:** 作為 Demo 負責人，我要在 Bedrock 或其他模組不可用時仍能完整走完流程，讓現場展示不會因單一依賴失效而中斷。

#### Acceptance Criteria

1. WHILE `USE_BEDROCK` 為 `false`，THE M5_Orchestrator SHALL 完成感知、決策與通報全流程，並在 Envelope `warnings` 記錄目前為保底模式。
2. IF Bedrock 模型呼叫失敗，THEN THE M5_Orchestrator SHALL 回傳 `status` 為 `partial` 的 Envelope，其 `DecisionResult` 仍包含 `traffic_level`、`route_plan`、`ete` 與 M4 模板產生的 `control_center_report` 與 `notifications`，並在 `errors` 加入 `code` 為 `MODEL_INVOCATION_FAILED` 的項目。
3. IF Knowledge Base 檢索失敗，THEN THE M5_Orchestrator SHALL 使用 M3 的本機 SOP 檢索結果，並在 `errors` 加入 `code` 為 `KNOWLEDGE_RETRIEVAL_FAILED` 的項目、在 `warnings` 記錄 `retrieval_source` 為 `local_fallback`。
4. WHILE M1–M4 尚未完成實作，THE M5_MockLayer SHALL 使四個 REST 端點與 `/ws` 回傳通過 `contracts/module_exchange_contract.json` 驗證的假資料。
5. WHEN `USE_STUB_MODULES` 為 `true`，THE M5_Orchestrator SHALL 對所有模組邊界使用 stub 實作並在 Envelope `warnings` 記錄為強制 stub 模式，不論真實模組是否可用。
6. WHEN 真實模組替換 M5_MockLayer，THE M5_Orchestrator SHALL 只變更資料來源函式，並使 API 回應的 Envelope 格式與 `payload` 型別維持不變。
7. THE M5_Dashboard SHALL 使 `data/live_incidents.json` 三筆事件各自可由事件注入面板完成一次評估，並顯示對應的決策依據、路線、建議書與簡訊。
8. IF 任一下游模組拋出未預期例外，THEN THE M5_Api SHALL 回傳 `status` 為 `error`、`errors[0].code` 為 `INTERNAL_ERROR` 的 Envelope，並使服務繼續接受後續請求。

---

## 不在本 spec 範圍

以下項目**不由本 spec 定義或實作**：

1. **共通資料流與契約語意**：Message Envelope 欄位語意、單位換算、Join／as-of 規則、SOP 門檻數值、分級門檻、ETE 公式、五個 canonical JSON 的欄位定義。以上皆見 `.kiro/steering/02-data-contract.md` 與 `contracts/module_exchange_contract.json`。
2. **M1 實作**：`src/loaders.py`、`src/rules.py`、`data_manifest.md`。
3. **M2 實作**：`src/routing.py`、`data/display_geometry.json` 的產生。
4. **M3 實作**：`src/agent.py`、`src/bedrock_service.py`、`prompts/**`、Knowledge Base 建置。
5. **M4 實作**：`src/reporting.py` 的 ETE 計算、建議書與簡訊模板。
6. **工程流程**：部署、壓力測試、多環境設定、CI/CD。
7. **存取控制**：登入、Cognito、角色權限。
8. **新增端點或新技術**：任何超出 `.kiro/steering/00-tech-stack.md` 第 1、4 節的框架、資料庫或端點。
