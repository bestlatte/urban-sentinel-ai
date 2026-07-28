# Implementation Plan — M5 決策編排、API 與 Dashboard

## Overview

實作語言為 Python 3.12 + 原生前端，依 `.kiro/steering/00-tech-stack.md`。

**任務 1–3 是全隊的阻塞點**：`src/models.py` 凍結後其他四位成員才能 import 型別；Mock 四端點與 `/ws` 骨架完成後 M1–M4 才有介接目標；前端骨架完成後才能一邊接真實資料一邊調版面。因此這三項必須先做完再開分支。

**可寫檔案**：`main.py`、`src/models.py`、`src/orchestrator.py`、`src/ws_manager.py`、`frontend/**`、`contracts/module_exchange_contract.json`、`tests/**`（M5 自己的測試）
**唯讀**：`src/loaders.py`、`src/rules.py`、`src/routing.py`、`src/agent.py`、`src/bedrock_service.py`、`src/reporting.py`、`prompts/**`、`data/**`

`P0` = Demo 核心路徑，必須完成；`P1` = 加分項，核心穩定後再做。標記 `*` 的子任務為測試，可略過以換取速度。

---

## Tasks

### 階段一：解除全隊阻塞（P0，最高優先）

- [ ] 1. [P0] 凍結 `src/models.py` 共用型別與 Envelope 建構
  - 依 `contracts/module_exchange_contract.json` 的 `$defs` 實作全部 Pydantic Model 與列舉（型別清單見 requirements 需求 1.1）
  - 實作 `build_envelope()` 單一入口，`correlation_id` 由呼叫方傳入，`schema_version` / `message_id` / `generated_at` 由函式產生
  - 所有時間欄位以 `Asia/Taipei`（`+08:00`）輸出
  - 建立 `pyproject.toml` 與 `.env.example`（欄位只引用 `.kiro/steering/00-tech-stack.md` 第 5 節，需含 `USE_STUB_MODULES`）
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.7_

- [ ]* 1.1 [P0] 撰寫 Envelope 與 payload 契約一致性性質測試
  - **Property 1: Envelope 與 payload 契約一致性**
  - 以 `jsonschema` 對機器契約驗證，涵蓋全部 `message_type` × payload 組合
  - **Validates: Requirements 1.2, 1.3, 1.5, 2.3, 2.4, 2.5, 9.4**

- [ ]* 1.2 [P0] 撰寫型別齊備與唯一定義處單元／靜態測試
  - 比對 `src/models.py` 匯出名稱集合；掃描 `src/` 其他檔案未重複定義契約型別名稱
  - _Requirements: 1.1, 1.7_

- [ ] 2. [P0] 建立 `main.py` 與 Mock 四端點、`/ws` 骨架
  - 建立 FastAPI 應用，掛載 `frontend/`（`StaticFiles(html=True)`）與 `/api` 前綴路由
  - 實作四個端點與 `/ws`，回應一律經 `build_envelope()`（`GET /api/health` 除外）
  - 在 `src/orchestrator.py` 內建立 `ModuleGateway` Protocol 與 `StubGateway`，以硬編假資料回傳各契約型別（不讀 `data/**`），並在 `warnings` 寫入 `module_stub_in_use:<module>`
  - 實作 `build_gateway()`：依 `USE_STUB_MODULES` 與 import 結果選擇 gateway（強制時 warning 記 `module_stub_in_use:forced`，import 失敗時個別降級）
  - 註冊統一例外處理器（`VALIDATION_ERROR` / `TIMEOUT` / `INTERNAL_ERROR`）
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.9, 9.4, 9.5, 9.6, 9.8_

- [ ]* 2.1 [P0] 撰寫路由白名單與 health 形狀單元測試
  - 比對 FastAPI 路由表；確認 `GET /api/health` 不帶 Envelope 欄位且含 `use_bedrock`
  - _Requirements: 2.1, 2.2, 2.6_

- [ ]* 2.2 [P0] 撰寫 gateway 替換不改回應形狀性質測試
  - **Property 30: 更換 gateway 不改變回應形狀**
  - **Validates: Requirements 9.6**

- [ ] 3. [P0] 建立前端骨架 `frontend/**`
  - `index.html`：依 design.md Grid 版面建立六個分區容器、事件注入 Modal、What-if 對話框、F2 彈窗容器
  - `css/styles.css`：深色指揮中心主題、以 CSS Variables 定義級別與路線色彩（依 `.kiro/steering/02-data-contract.md` 第 8 節）、運算中動畫（單次循環 ≤ 2 秒）
  - `js/api.js`：Fetch 四端點、Envelope 拆封、錯誤碼轉可讀訊息
  - `js/ws.js`：`/ws` 連線、指數退避重連、斷線時輪詢 `GET /api/dashboard`、依 `message_type` 分派
  - `js/app.js`：單一狀態物件與渲染排程，先以 Mock 回應渲染全部分區
  - `js/charts.js`、`js/map.js`：先建立空實作與呼叫介面
  - `vendor/`：落地 Chart.js，`index.html` 以相對路徑引用
  - _Requirements: 7.1, 7.10, 7.12, 6.6_

- [ ]* 3.1 [P0] 撰寫前端靜態檢查
  - 掃描 `frontend/js/*.js` 不含門檻常數（0.95／0.85）與 ETE 公式；`styles.css` 動畫時長 ≤ 2s；`index.html` 的 Chart.js 指向 `vendor/`
  - _Requirements: 7.2, 7.10, 7.11, 7.12_

- [ ] 4. [P0] 檢核點 — 骨架可展示
  - 以 `uvicorn main:app --reload` 手動開啟後確認四端點回應通過契約驗證、前端六個分區以假資料完整顯示
  - 確保所有測試通過，有疑問請詢問使用者

---

### 階段二：A1 分類與 A2 編排（P0）

- [ ] 5. [P0] 實作 A1 事件分類器
  - 在 `src/orchestrator.py` 實作 `ClassificationResult` 與查表式分類（對照表見 design.md Data Models 節）
  - 受影響路段來源優先序：`affected_road` 優先於 `RD_` 類 `affected_segment`
  - 未知事件型別：`requires_rerouting=false` + warning，流程繼續
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9_

- [ ]* 5.1 [P0] 撰寫 A1 分類對照表與幂等性質測試
  - **Property 3: A1 分類等於對照表且幂等**
  - **Validates: Requirements 3.1, 3.2, 3.3, 3.5, 3.6, 3.8, 3.9**

- [ ]* 5.2 [P0] 撰寫受影響路段來源優先序性質測試
  - **Property 4: 受影響路段來源優先序**
  - **Validates: Requirements 3.4**

- [ ] 6. [P0] 實作 A2 編排主流程與 `DecisionResult` 組裝
  - 依 design.md 時序圖串接 gateway：`load_data` → `evaluate_rules` → A1 → （條件）`plan_routes` → `calculate_ete` ‖ `run_agent` → `generate_report`
  - 以 `asyncio.gather` 併發 ETE 與 advisory；每個呼叫包 `asyncio.wait_for`，逾時常數集中於 `TimeoutBudget`
  - 組裝時以 Python 事實欄位為最終值，忽略 advisory 同名內容；設定 `fact_source`
  - 量測 `duration_ms` 並設定 `within_60_second_sla`
  - `requires_rerouting=false` 時 `route_plan=None` 且流程繼續
  - 建立並貫穿單一 `correlation_id`
  - _Requirements: 1.4, 3.7, 4.1, 4.2, 4.3, 4.6, 4.7, 4.9_

- [ ]* 6.1 [P0] 撰寫事實欄位不被 LLM 改動性質測試
  - **Property 12: LLM 不得改動事實欄位**
  - **Validates: Requirements 4.6, 4.7**

- [ ]* 6.2 [P0] 撰寫事實欄位等於下游輸出性質測試
  - **Property 9: 事實欄位等於下游輸出**
  - **Validates: Requirements 4.2**

- [ ]* 6.3 [P0] 撰寫編排呼叫順序性質測試
  - **Property 8: 編排呼叫順序**
  - **Validates: Requirements 4.1**

- [ ]* 6.4 [P0] 撰寫 correlation_id 一致性性質測試
  - **Property 2: 單一流程共用 correlation_id**
  - **Validates: Requirements 1.4**

- [ ]* 6.5 [P0] 撰寫 SLA 旗標一致性與 rule_hits 保存性質測試
  - **Property 14: SLA 旗標與量測值一致**
  - **Property 5: rule_hits 完整保存**
  - **Validates: Requirements 4.9, 3.7**

- [ ]* 6.6 [P0] 撰寫不需改道時流程仍完整性質測試
  - **Property 10: 不需改道時流程仍完整**
  - **Validates: Requirements 4.3**

- [ ] 7. [P0] 實作多語通報觸發與模板退回
  - 依 M1 的 SOP-6 命中結果決定是否要求 M4 產生多語 `Notification`（門檻值不在 M5 比較）
  - advisory 缺 `sop_evidence` 或未含 Python 事實值時改用 M4 模板，並寫入 warning
  - _Requirements: 4.4, 4.5, 4.8_

- [ ]* 7.1 [P0] 撰寫多語通報雙向對應性質測試
  - **Property 11: 多語通報與 SOP-6 門檻雙向對應**
  - **Validates: Requirements 4.4, 4.5**

- [ ]* 7.2 [P0] 撰寫不合格 advisory 退回模板性質測試
  - **Property 13: 不合格 advisory 退回模板**
  - **Validates: Requirements 4.8**

- [ ] 8. [P0] 實作錯誤與降級處理
  - 未知 `event_id` → `DATA_NOT_FOUND`；請求驗證失敗 → `VALIDATION_ERROR` + `field`
  - 下游失敗或逾時 → `partial` + 對應錯誤碼 + warning 記錄模組，事實欄位保留
  - 逾時兩級處置（依 design.md Components 第 4 節）
  - 未預期例外 → `INTERNAL_ERROR`，服務存活
  - _Requirements: 2.7, 2.8, 2.9, 4.10, 9.2, 9.3, 9.8_

- [ ]* 8.1 [P0] 撰寫錯誤碼映射性質測試
  - **Property 6: 錯誤輸入映射到正確錯誤碼且服務存活**
  - **Validates: Requirements 2.7, 2.9, 9.8**

- [ ]* 8.2 [P0] 撰寫下游失敗降級性質測試
  - **Property 7: 下游失敗降級**（含 `FailingGateway` 生成器）
  - **Validates: Requirements 2.8, 4.10, 9.2, 9.3**

- [ ] 9. [P0] 檢核點 — 編排可跑通
  - 確保所有測試通過，有疑問請詢問使用者

---

### 階段三：A4 留痕與 WebSocket（P0）

- [ ] 10. [P0] 實作 A4 決策留痕
  - 在 `src/orchestrator.py` 實作 `DecisionTrace`（記憶體 `dict[event_id, TraceEntry]`），寫入整份 `DecisionResult` 含報告與簡訊全文
  - 保存 A2 工具呼叫順序與引用 `clause_id` 清單
  - 同 `event_id` 覆寫；寫入失敗只加 warning
  - What-if 流程不呼叫留痕
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [ ]* 10.1 [P0] 撰寫留痕 round-trip 性質測試
  - **Property 16: 決策留痕 round-trip**
  - **Validates: Requirements 5.1, 5.4**

- [ ]* 10.2 [P0] 撰寫軌跡 last-write-wins 性質測試
  - **Property 17: 決策軌跡為 last-write-wins map**
  - **Validates: Requirements 5.2, 5.3**

- [ ]* 10.3 [P0] 撰寫留痕失敗不中斷與重複評估決定性性質測試
  - **Property 18: 留痕失敗不中斷回應**
  - **Property 15: 重複評估的決定性**
  - **Validates: Requirements 5.5, 4.12**

- [ ] 11. [P0] 實作 `src/ws_manager.py` 的 `ConnectionManager`
  - `set` 保存連線；`connect` / `disconnect`（重複移除安全）/ `broadcast`（失效即移除並繼續，回傳送達數）
  - `/ws` 端點單向：`receive_text()` 僅偵測斷線，內容丟棄
  - 四個廣播時機接入編排：`rules.evaluated.v1`、`decision.completed.v1`、`dashboard.updated.v1`、`whatif.evaluated.v1`，與 REST 共用 payload 與 `correlation_id`
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.8, 2.10_

- [ ]* 11.1 [P0] 撰寫連線集合 model-based 性質測試
  - **Property 20: 連線集合等於參考模型**
  - **Validates: Requirements 6.1, 6.2, 6.8**

- [ ]* 11.2 [P0] 撰寫推播內容等於 REST 與上行無副作用性質測試
  - **Property 21: 推播內容等於 REST 內容**
  - **Property 22: 上行訊息無副作用**
  - **Validates: Requirements 6.3, 6.4, 6.5**

- [ ]* 11.3 [P0] 撰寫 REST 回應欄位自足性質測試
  - **Property 23: REST 回應欄位自足**
  - **Validates: Requirements 6.7, 7.6, 7.7, 7.8**

- [ ] 12. [P0] 檢核點 — 推播與留痕可用
  - 確保所有測試通過，有疑問請詢問使用者

---

### 階段四：Dashboard 呈現（P0）

- [ ] 13. [P0] 實作 `js/app.js` KPI 與狀態渲染
  - 以 `DashboardPayload.kpis` 欄位直接渲染 KPI 卡片；`traffic_level` 值對應 CSS class，不在 JS 比較門檻
  - `crowd_data_classification` 為 `demo` 時標示「Simulated / Demo Scenario」；為 `unavailable` 時顯示「資料未提供」
  - `partial` 回應時仍渲染既有欄位，缺值區塊顯示「資料未提供」
  - _Requirements: 7.2, 7.8, 7.9, 7.11_

- [ ] 14. [P0] 實作 `js/charts.js` 時序圖
  - Chart.js 繪製車流與人流時序圖，標示 `.kiro/steering/02-data-contract.md` 第 4 節門檻線
  - 人流圖表加 Demo 標示
  - _Requirements: 7.3, 7.8_

- [ ] 15. [P0] 實作 `js/map.js` SVG 路網拓樸圖
  - 依 `display_geometry.json` 的 `display_points` 定位（唯讀取用，不參與決策）
  - 依級別與路線色彩規則上色：主路線亮綠實線、次路線黃色虛線、封閉路段紅色粗線
  - _Requirements: 7.4, 7.11_

- [ ] 16. [P0] 實作事件注入面板、決策依據面板與建議書／簡訊卡片
  - 事件注入面板列出 `available_incidents`，送出後呼叫 `POST /api/incidents/evaluate` 並更新畫面
  - 決策依據面板顯示每筆 `RuleHit` 的 `clause_id` 與條款內容、每個 `candidates` 的排除／保留理由
  - 建議書卡片顯示 `control_center_report` 全文；簡訊卡片顯示每筆 `Notification` 的語言、通道與 `content` 全文
  - F2 異常彈窗：收到 `rules.evaluated.v1` 且含 `alerts` 時顯示
  - _Requirements: 7.5, 7.6, 7.7, 6.6_

- [ ] 17. [P0] 檢核點 — 單頁畫面完整
  - 確保所有測試通過，有疑問請詢問使用者

---

### 階段五：What-if 編排（P0）

- [ ] 18. [P0] 實作 What-if 編排流程
  - 驗證 `scenario_overrides` 非空（空 → `VALIDATION_ERROR`）
  - 順序：`parse_whatif` → 記憶體副本套用覆寫 → M1／M2／M4 重算 → `narrate_whatif`
  - 事實欄位一律取重算輸出；`simulation_only` 固定 true
  - 以 `deepcopy` 的 bundle 套用覆寫，不改 `data/**`、不呼叫 A4
  - 計算 `differences_from_base`（無 `base_decision_id` 時以 `base_as_of` 現況為基準）
  - `parse_whatif` 失敗 → `MODEL_INVOCATION_FAILED` + warning 提示改用明確覆寫參數
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 5.6_

- [ ]* 18.1 [P0] 撰寫 What-if 旗標與呼叫順序性質測試
  - **Property 24: What-if 的模擬旗標與呼叫順序**
  - **Validates: Requirements 8.1, 8.2**

- [ ]* 18.2 [P0] 撰寫 What-if 事實來自重算性質測試
  - **Property 25: What-if 事實欄位來自重算**
  - **Validates: Requirements 8.3**

- [ ]* 18.3 [P0] 撰寫不改動來源資料與不留痕性質測試
  - **Property 27: What-if 不改動來源資料**
  - **Property 19: What-if 不改動決策軌跡**
  - **Validates: Requirements 8.6, 8.9, 5.6**

- [ ]* 18.4 [P0] 撰寫差異清單對應與空覆寫錯誤性質測試
  - **Property 26: 差異清單與重算結果對應**
  - **Property 28: 空覆寫視為驗證錯誤**
  - **Validates: Requirements 8.4, 8.5, 8.7**

- [ ] 18a. [P0] [2026-07-28新增] 實作 `POST /api/what-if` 的回溯追問／無週期分支（`TraceAnswer`）
  - 此任務原本在 tasks.md 定案時遺漏——`SPEC-O3` §4 定義 `POST /api/what-if` 有三種路由分支，前兩個任務只做了「前瞻假設」分支（走 M1/M2/M4 重算），這裡補上另外兩種：
    - 問題不含前瞻假設詞、且 `current_trace_id` 非 null → 呼叫 M4B 的 `answer_trace_query(trace_id, question)`，回傳 `message_type="trace.answered.v1"`、`payload=TraceAnswer{trace_id, answer_text}`
    - 問題不含前瞻假設詞、且 `current_trace_id` 為 null → 回傳固定文字（「目前無進行中的決策週期可查詢...」），同樣包成 `TraceAnswer{trace_id: null, answer_text: 固定文字}`
  - 前瞻詞優先於回溯（問題同時含兩者 → 走 What-if 分支，不進這裡）
  - 這個分支**不呼叫 A4**、**不寫決策軌跡**，純讀取既有 trace 資料
  - _Requirements: 2.5a（見 requirements.md 補註）_

- [ ] 19. [P0] 實作 `js/app.js` 的 What-if 對話框
  - 送出問句與可選覆寫參數至 `POST /api/what-if`
  - 顯示重算後 `rule_hits`、SOP 依據、`differences_from_base` 與敘述文字，並明確標示為模擬結果
  - _Requirements: 7.1, 8.1, 8.4_

- [ ] 20. [P0] 檢核點 — What-if 可跑通
  - 確保所有測試通過，有疑問請詢問使用者

---

### 階段六：真實模組串接與保底驗收（P0）

- [ ] 21. [P0] 以 `LiveGateway` 串接 M1–M4
  - 依 `ModuleGateway` Protocol 實作 `LiveGateway`，逐一替換 stub 方法；缺失模組個別降級並保留 warning
  - 確認 Envelope 格式與 payload 型別未因換來源而改變
  - _Requirements: 9.4, 9.6_

- [ ] 22. [P0] 實作保底模式編排路徑
  - `USE_BEDROCK=false` 時走 M3 本機檢索 + M4 模板，寫入 `fallback_mode` warning，事實欄位仍齊備
  - _Requirements: 9.1, 9.2, 9.3_

- [ ]* 22.1 [P0] 撰寫保底模式仍產出完整事實性質測試
  - **Property 29: 保底模式仍產出完整事實**
  - **Validates: Requirements 9.1**

- [ ]* 22.2 [P0] 撰寫三筆事件固定驗收值回歸測試
  - 以 `data/live_incidents.json` 三筆事件執行完整編排，期望值引用 `.kiro/steering/02-data-contract.md` 第 6 節驗收表（主因 SOP、主／次路線、排除理由、`ete_minutes`、`estimated_recovery_at`）
  - _Requirements: 4.11, 9.7_

- [ ] 23. [P0] 建立 Demo 人工檢核清單
  - 在 spec 目錄新增檢核清單，涵蓋設計中列為人工驗證的項目：Chart.js 門檻線、SVG 上色、事件注入互動、`unavailable` 文案、斷線重連與輪詢、六個分區存在，以及三筆事件各完整操作一次
  - _Requirements: 6.6, 7.1, 7.3, 7.4, 7.5, 7.9, 9.7_

- [ ] 24. [P0] 最終檢核點 — 全流程可展示
  - 確保所有測試通過，有疑問請詢問使用者

---

### 階段七：加分項（P1）

- [ ] 25. [P1] 多語通報的日文／韓文顯示
  - 簡訊卡片支援 `ja`、`ko` 的語言標籤與字型排版（內容仍由 M4 產生）
  - _Requirements: 4.4, 7.7_

- [ ] 26. [P1] 動畫與視覺細節強化
  - 級別變更時的卡片轉場、路線繪製的漸進動畫、F2 彈窗進出效果（單次循環仍 ≤ 2 秒）
  - _Requirements: 7.10_

- [ ] 27. [P1] 擴充 What-if 預設問句
  - 在對話框提供更多預設問句按鈕，皆走既有 `POST /api/what-if`，不新增端點
  - _Requirements: 8.2, 8.4_

---

## Notes

- 標記 `*` 的子任務為測試，可略過以換取速度；核心實作任務不得標記為可略過。
- 任務 1–3 完成前不要開始階段二之後的工作，因為其他四位成員被它們阻塞。
- 所有任務只寫入 M5 擁有的檔案；需要其他模組行為變更時，改為在 `ModuleGateway` 提出簽章需求，不直接修改對方檔案。
- 共通資料流、門檻數值與 ETE 公式一律引用 steering，不在程式碼或測試中複製字面值（門檻比較由 M1／M4 負責）。
- 本計畫不含部署、壓力測試、多環境設定與 CI/CD。
