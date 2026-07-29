# Kiro 開發總清單 — 遵守事項 + 逐檔開發順序

> **這份文件是給 Kiro 執行用的操作手冊，不是規格本身**（規格在 `.kiro/steering/`、
> `.kiro/specs/`）。這裡只規定「做事的規矩」跟「先做哪個、後做哪個」。

## 🛑 最高規則：一次只做一個打勾項目，做完立刻停下來回報，等確認才能繼續

**不是做完一整個 Phase 才回報，是做完下面清單裡的每一個 `- [ ]` 項目就要停。**

每完成一項，依這個格式回報，然後停下來等人類回覆才能繼續下一項：

```
✅ 已完成：[項目名稱]
- 讀的 spec：[檔案路徑]
- 寫的檔案：[檔案路徑]
- 對應的驗收測試：[tests/xxx.py::test_name，是否已經能跑]
- 不確定/需要確認的地方：[如果有，明講；沒有就寫「無」]

等待確認後繼續下一項。
```

不得因為「反正接下來的項目看起來很直覺」就跳過確認、連續做兩項以上。不得為了效率把多個檔案的內容一起生成再一次回報——那違反這份清單存在的目的（讓人類能逐步審查，而不是事後面對一大包看不完的 diff）。

---

## 一、開發注意事項（每個項目都適用，不是只講一次就算）

1. **動手前先讀完整份 spec，不要看一半就寫。** 每個打勾項目後面標的 spec 路徑，要讀「該文件的全文」，不是只看函式簽章那一段——驗收測試章節尤其不能跳過，測試案例之間常常互相補充邊界情況（例如 `m1-data-ingestion` 的測試 #6 跟 #6b）。
2. **驗收測試是規格的一部分，不是事後才補。** 每個 `src/*.py` 完成時，同一個打勾項目要連同 `tests/test_*.py` 一起做完，不是分開兩個項目。`tests/` 底下已經有鷹架（大部分是 `pytest.skip(...)`），把它們改成真正的 `assert`，不是重寫一份新的。
3. **golden value 用精確值斷言，不是「差不多對」。** ETE 必須是 90/70/41 分鐘，不是「約90分鐘」；`retrieval_source`／`ReasonCode`／`message_type` 這些欄位名稱、列舉值，一個字元都不能跟 `src/models.py`、`.kiro/steering/04-system-architecture.md` §5-6 對不上。
4. **不確定 spec 有沒有衝突或缺漏時，停下來問，不要自己猜一個答案填上去。** 這份清單裡標了「[待確認]」的項目，代表連總架構師都還沒有定案，你的任務是照著已經寫的原型調整或提出問題，不是照抄了事也不是自己重新設計一套。
5. **跨模組存取一律經由 `src/orchestrator.py` 的 `GATEWAY`（`ModuleGateway`），不要繞過去直接 import。** 這條規則在鷹架階段就因為疏忽被違反過一次（`orchestrator.py` 的函式沒接 `GATEWAY`、`main.py` 建的 `GATEWAY` 跟 `orchestrator.py` 的是兩個變數），已經修正，**不要在後續開發中再犯同樣的錯**——每次新增一個會呼叫 M1/M2/M3/M4 的函式，先檢查是不是該透過 `GATEWAY` 存取。
6. **Docstring 只寫「為什麼」，不寫「做什麼」。** 函式名跟型別簽章已經說明 what；不直覺的設計決策才需要註解（見 `.kiro/steering/03-testing-and-ai-collaboration.md` §3）。
7. **完成一個檔案後，實際 `import` 一次或跑一次測試，不要只憑「看起來對」就回報完成。** 鷹架階段就是因為沒有實際跑過，才漏掉 `GATEWAY` 沒接線、例外處理器沒掛上這兩個問題——這是慘痛教訓，不要重演。
8. **不確定該用哪個套件版本、要不要新增依賴時，先檢查 `pyproject.toml` 是否已經列了；沒列到的套件，先問，不要自己 `pip install` 一個沒人同意過的東西。** 對照 `.kiro/steering/00-tech-stack.md` 的固定技術棧與明確禁止清單。
9. **不要修改 `.kiro/steering/`、`.kiro/specs/` 底下的任何文件內容**，除非是在對應的打勾項目裡明確要求你回頭修正 spec（例如發現 `[INFERRED]` 欄位跟實際需求對不上）。這些是總架構師審查過的產物，如果你發現裡面有問題，回報、不要自己改。
10. **禁用清單是硬性的，不是建議。** 不用 React/Vue/Vite、不用 PostgreSQL/Redis/Neptune、不新增 REST 端點、不用 Cognito 登入——`00-tech-stack.md` §2 完整清單。

---

## 二、逐檔開發順序（工程邏輯：先建無依賴的基礎型別，再由下而上組裝，最後才接前端與整合）

排序原則說明（業界標準的相依關係排序，不是隨意編排）：
- **先型別、後邏輯**：`models.py` 是所有模組的共同語言，必須第一個定案。
- **先純函式、後有副作用的整合層**：D1-D4/P1-P5/R1-R5/A3/C1-C4 都是零狀態、零外部依賴的純計算，最容易獨立驗證，排在最前面；`orchestrator.py`（會呼叫多個模組、有狀態）排在後面。
- **先本機、後雲端**：K3 的 `local_fallback.py`/`sop_data.py`（零依賴）先於 `bedrock_kb.py`（依賴AWS）；`USE_BEDROCK=false` 保底路徑要先能動，雲端路徑是疊加上去的能力，不是反過來。
- **先葉節點、後組裝節點**：`agent/` 底下的工具跟格式化函式先做，`whatif_agent.py`（組裝以上全部）最後做；`ws_manager.py`／`main.py` 依賴前面全部模組，排最後。
- **後端先於前端**：前端是「把後端已經算好的事實顯示出來」，後端的資料形狀（`DecisionResult`／`WhatIfResult`／`TraceAnswer`）沒有先穩定下來，前端寫了也會被迫重寫。
- **每個 Phase 內部也照相依順序排**，不是同一個 Phase 裡的項目可以隨意調換順序做。

### Phase 0：基礎型別（已由總架構師完整實作，Kiro 的任務是覆核，不是重寫）

- [x] **0.1** 覆核 `src/models.py`：對照 `.kiro/steering/02-data-contract.md`、各模組 spec，確認沒有 `[INFERRED]` 標記的欄位跟你即將要寫的邏輯對不上；跑 `pytest tests/test_models.py` 確認 4 條全過。
- [x] **0.2** [2026-07-28已定案，見Kiro第一輪審查回覆] `KpiSummary`、`differences_from_base` 已定案（見 §2.3 KPI定義、`whatif_engine.diff_from_base()` docstring）；`EvidenceRef` 仍是 `[INFERRED]`，實作到 Phase 1（P4規則引擎）時如發現形狀不夠用才回報。

### Phase 1：M1 資料感知與規則（零外部依賴的純函式）

- [x] **1.1** `src/loaders.py`（D1-D4）+ `tests/test_loaders.py`。Spec：`.kiro/specs/m1-data-ingestion/requirements.md` 全文。特別注意真實 CSV 的 `%` 字串解析（測試#1/#2）。
- [x] **1.2** `src/rules.py`（P1-P5）+ `tests/test_rules.py`。同一份 spec。特別注意 SOP-1 全15路段分級 vs 城市應變觸發限定2段的區分（測試#6/#6b 都要留著）。

### Phase 2：M2 路網規劃（純函式，依賴 Phase 1 的型別但不依賴其實作）

- [x] **2.1** `src/routing.py` 的 `plan_route()`（R1-R5）+ `tests/test_routing.py`。Spec：`.kiro/specs/m2-incident-routing/模組2C_本機路網重規劃引擎_第一階段Spec.md` 第4-6節。九種 `ReasonCode` 用 `SPEC-00` §3.3 的命名。
- [x] **2.2** `src/routing.py` 的 `count_affected_intersections()`（`COUNT_INTERSECTIONS`）。同一份 spec 檔頭補註。
- [x] **2.3** [2026-07-28已定案，回應Kiro審查] `data/display_geometry.json` 已由總架構師產出（15路段的示意座標，viewBox 0 0 800 600，邏輯見檔案內 `$comment`），覆核即可，如果團隊對版面配置有意見可以調整座標值，但不要整個重新設計座標系統。

### Phase 3：M4 ETE 與報告生成

- [x] **3.1** `src/reporting.py` 的 `calculate_ete()` + 對應測試。Spec：`.kiro/specs/m4-decision-reporting/requirements.md` 第二節。三筆黃金值（90/70/41分）精確斷言。
- [x] **3.2** `src/reporting.py` 的 `generate_report()`（C1-C4）+ 對應測試。同一份 spec 第三節；提示詞讀 `prompts/report.txt` + `prompts/notification.txt`，不要硬編在程式碼裡。

### Phase 4：M3 子套件（本機優先，雲端疊加）

- [x] **4.1** `src/bedrock_service/sop_data.py`（SOP JSON 預載）。Spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第六節。
- [x] **4.2** `src/bedrock_service/local_fallback.py`（本機關鍵字比對，`KEYWORD_MAP` 已經是完整資料，只需實作比對函式）+ `tests/test_sop_retriever.py` 的本機部分。同一份 spec 第四節。
- [x] **4.3** `src/bedrock_service/bedrock_kb.py`（雲端呼叫）。同一份 spec 第三節。**需要 AWS Bedrock model access 已開通**，未開通前可以先跳過，不影響 4.4。
- [x] **4.4** `src/bedrock_service/sop_retriever.py`（`query_sop()` 主邏輯 + 模式切換，含 `try/except` 真的退化）+ 補完 `tests/test_sop_retriever.py` 剩餘測試。同一份 spec 第五節。
- [x] **4.5** `src/session/models.py` 覆核（已是完整 dataclass，不太需要改動）。
- [x] **4.6** `src/session/session_manager.py`（`handle_message`/`record_response`/`clear_session`）+ `tests/test_session_manager.py`。Spec：`.kiro/specs/m3-bedrock-advisor/W2-session-manager/design.md`。

### Phase 5：解釋鏈記錄與生成層

- [x] **5.1** `src/decision_trace.py` 的 `open_trace()`/`record_step()`。Spec：`.kiro/specs/m4-explanation-chain-and-orchestrator/SPEC-M4A_解釋鏈_記錄層.md` 第4節，含全部十項驗收測試。
- [x] **5.2** `src/decision_trace.py` 的 `resolve_segment_id()`/`generate_report_explanation()`/`answer_trace_query()`。Spec：`SPEC-M4B_解釋鏈_生成層.md`。

### Phase 6：What-if 覆寫重算引擎（依賴 Phase 1-3 的純函式都已完成）

- [x] **6.1** `src/whatif_engine.py` 的 `apply_scenario_overrides()`。entity 前綴（`BS_`/`RD_`）對應到 bundle 哪個欄位，實作時逐一核對 `.kiro/steering/02-data-contract.md` §2-3 的欄位表（找不到對應 entity 要拋 ValueError，不要靜默忽略）。
- [x] **6.1b** `src/whatif_engine.py` 的 `diff_from_base()`（`WhatIfResult.differences_from_base` 的計算邏輯，已定案：固定比對 traffic_level/ete.minutes/主次路線segment_id/觸發SOP clause_id集合四項，見函式docstring）。
- [x] **6.2** `src/whatif_engine.py` 的 `run_scenario()` 覆核——確認呼叫的是 `gateway.evaluate_rules()`/`gateway.plan_routes()`/`gateway.calculate_ete()`（透過 Gateway），不是直接 import Phase 1-3 的函式。

### Phase 7：W1 Agent（依賴 Phase 4 的 K3、Phase 6 的 whatif_engine）

- [x] **7.1** 確認 `src/agent/system_prompt.py` 能正確讀到 `prompts/advisor.txt`（已是完整實作，跑一次 import 驗證即可）。
- [x] **7.2** `src/agent/loading.py` 的 loading 步驟推播邏輯（方案B兩段式，見 design.md 第十一節）。
- [x] **7.3** `src/agent/tools.py` 的 `query_sop`（已接好 `bedrock_service`，覆核即可）。
- [x] **7.4** `src/agent/tools.py` 的 `_get_current_context()`。[2026-07-28已定案] 已實作：透過 `orchestrator._current_trace_ctx`（contextvar，由 `handle_user_query()` 設定）取得 trace_id，查 `GlobalState.active_incidents` 找對應 `IncidentRecord`；trace_id為None時只回傳 `(None, GATEWAY.load_data())`。覆核程式碼即可，不用重新設計。依賴 Phase 8.1-8.6 的 `GlobalState`/`GATEWAY` 先做完。
- [x] **7.5** `src/agent/response_formatter.py` 的 `format_response()`。Spec：`W1-whatif-agent/design.md` 第七、八節。
- [x] **7.6** `src/agent/whatif_agent.py` 全部函式（`create_whatif_agent`/`_build_prompt`/`process_whatif`/`process_whatif_request`）。同一份 spec 第五、六、十節。**需要 Strands SDK 已安裝、Bedrock model access 已開通**。

### Phase 8：Orchestrator（依賴前面全部模組）

- [x] **8.1** `src/orchestrator.py` 的 `StubGateway` 全部方法（[2026-07-28已定案] 固定用 ACC_001 黃金情境反推假資料，見 `StubGateway` docstring 裡每個方法要回什麼值，不要自己編一組跟黃金值對不上的數字）。Spec：`m5-api-orchestrator-dashboard/design.md` 第2節。
- [x] **8.2** `src/orchestrator.py` 的 `LiveGateway` 全部方法（串接 Phase 1-4 的真實模組）。同一份 spec。**注意**：`ModuleGateway` 已移除 `parse_whatif`/`narrate_whatif` 兩個方法（跟W1實際的Strands Agent設計重複、從未被呼叫，已刪除，不要實作它們）。
- [x] **8.3** `src/orchestrator.py` 的 `classify_incident()`（A1）。已對照真實SOP文字確認過對照表，直接照 docstring 實作即可，不需要重新設計。
- [x] **8.4** `src/orchestrator.py` 的 `handle_trigger_batch()`（規則觸發靜態分派表）。Spec：`SPEC-O2` §2。**呼叫端已定案**：這個函式沒有對應REST端點，由 Phase 9 在 `main.py` 啟動時註冊的背景排程任務呼叫（見函式docstring），不是bug，Phase 9 會補上呼叫端。
- [x] **8.5** `src/orchestrator.py` 的 `handle_incident()`（七階段生命週期）。Spec：`SPEC-O1` 全文 + `SPEC-O2` §3（事件注入LLM規劃器）。OPEN階段要寫入 `_STATE.active_incidents[event.event_id] = IncidentRecord(trace_id=..., incident=event, bundle_snapshot=GATEWAY.load_data())`（見 `IncidentRecord`/`GlobalState` dataclass 定義），這是 7.4 能運作的前提。
- [x] **8.6** `src/orchestrator.py` 的 `get_global_state()`/`reset()`。[2026-07-28已定案] 已實作完成（回傳/重置模組層級的 `_STATE`），覆核即可不用重寫。
- [x] **8.7** 覆核 `handle_user_query()`（三分支路由邏輯、`_current_trace_ctx.set()` 已經是完整實作，這裡只需確認跟 Phase 7 的 W1、Phase 5 的 M4B 接得起來）。

### Phase 9：外殼（依賴前面全部模組）

- [x] **9.1** `src/ws_manager.py` 的 `ConnectionManager` 全部方法。
- [x] **9.2** `main.py` 的 `GET /api/dashboard`。
- [x] **9.3** `main.py` 的 `POST /api/incidents/evaluate`。
- [x] **9.4** `main.py` 的 `POST /api/what-if`（三分支回應形狀，見 `.kiro/steering/04-system-architecture.md` §5）。
- [x] **9.5** `main.py` 的 `GET /api/health`。
- [x] **9.6** `main.py` 的 `unified_exception_handler` 內容（骨架已掛上，補完錯誤碼映射邏輯）。
- [x] **9.7** `main.py` 的 7 個 WebSocket 廣播時機接入 `orchestrator.py`／`ws_manager.py`（見 `04-system-architecture.md` §5 總表）。
- [x] **9.8** [2026-07-28新增，回應Kiro審查] `main.py` 註冊背景排程任務（`@app.on_event("startup")` 或 `asyncio.create_task`），定期呼叫 `GATEWAY.evaluate_rules()` 掃全部路段、比對上次結果找新的 rule_hits（尤其B/A級轉換），組成 `TriggeredRule[]` 呼叫 `orchestrator.handle_trigger_batch()`——這是 8.4 的唯一呼叫端，demo資料時間跨度短，先求「啟動時跑一次」能動即可，不強求真的定時輪詢。

### Phase 10：前端（後端資料形狀穩定後才做，由小到大：工具函式→狀態→渲染→頁面組裝）

- [x] **10.1** `frontend/css/*.css` 全部 6 個檔案（`chat-variables.css` 已完整，其餘覆核並補完）。
- [x] **10.2** `frontend/js/chat-utils.js`（`escapeHtml`/`formatTime`）。
- [x] **10.3** `frontend/js/chat-state.js`（`ChatState` + 收合/拖拉，design.md 已有完整程式碼可抄）。
- [x] **10.4** `frontend/js/chat-render.js`（渲染函式，design.md 已有完整程式碼可抄，注意B級用橘色不是黃色）。
- [x] **10.5** `frontend/js/api.js`（Fetch 四端點）。
- [x] **10.6** `frontend/js/ws.js`（連線 + message_type 分派）。
- [x] **10.7** `frontend/js/chat-app.js`（`sendMessage()` 呼叫 REST，不是WS）。
- [x] **10.8** `frontend/js/charts.js`。
- [x] **10.9** `frontend/js/map.js`。
- [x] **10.10** `frontend/js/app.js`（KPI/F7分頁/F2彈窗/F5報告卡片，[待確認]項目見 `index.html` 內補註的業界通用版原型，可依團隊意見調整版面但資料形狀不能變）。
- [x] **10.11** `frontend/index.html` 最終走查——所有 `<script>`/`<link>` 路徑正確、六分區+F6面板都對應到已完成的JS函式。
- [x] **10.12** 手動下載 Chart.js 放進 `frontend/vendor/`（見該資料夾 README）。

### Phase 11：整合驗證（不寫新程式碼，是驗收關卡）

- [x] **11.1** `USE_STUB_MODULES=true` 跑 `uvicorn main:app --reload`，確認四端點回應通過契約驗證、前端六分區以假資料完整顯示。
- [x] **11.2** `USE_STUB_MODULES=false`（真實模組）跑三筆黃金事件（ACC_001/EVT_002/EVT_003），逐項比對 `.kiro/steering/04-system-architecture.md` §8 黃金驗收表。
- [x] **11.3** `USE_BEDROCK=false` 保底模式重跑三筆事件，確認完整流程不中斷。
- [x] **11.4** 全部 `tests/` 通過（`pytest tests/ -v`），確認沒有殘留的 `pytest.skip`。

### Phase 12：架構複查修正（2026-07-28，見 `.kiro/specs/architecture-reference/2026-07-28_架構圖合規性複查與待辦.md`）

> **排序原則**：這個 Phase 移到 Phase 11（整合驗證）之後、原本的「加分項」之前，因為
> 12.1 修的是模組1「動態時序監測儀表板」本身就該有的核心行為（不是額外加分），先把
> 核心的完整性補齊，再去做真正的加分項（現 Phase 13）才符合工程邏輯——不應該讓
> 「錦上添花」排在「本來就該做完」前面。
>
> 這份清單是總架構師重新逐字比對四份架構圖（三份邏輯架構圖 + 一份AWS部署分層圖）跟
> 現有程式碼後，找到的「文件/架構圖有畫，程式碼沒真的接上」的落差，跟 `INDEX.md`
> 記錄的 `ModuleGateway` 早期未接線問題是同一種根因。

- [x] **12.1** `main.py` 的 `_periodic_rule_monitor()` + `_start_periodic_rule_monitor()`。對應
  `2026-07-28_架構圖合規性複查與待辦.md` §2.1：模組1「動態時序監測儀表板」目前只在伺服器
  啟動時跑一次規則評估，不符合架構圖「後端每 5~15 秒推進一次並主動推播」的要求。演算法
  已經完整寫在 `_periodic_rule_monitor()` 的 docstring 裡（睡眠→評估→比較上一輪→有轉換才
  推播），照著實作即可，不需要重新設計。**注意**：`_start_periodic_rule_monitor()`目前是
  `pass`（刻意不擋住伺服器啟動），Kiro 完成 `_periodic_rule_monitor()` 後記得把這裡改成
  `asyncio.create_task(_periodic_rule_monitor())`，兩個函式要一起完成才算數，不能只做一半。
  完成後重新跑一次 Phase 11 的 11.1/11.4（伺服器能啟動、`pytest tests/ -v` 全過），確認
  背景任務沒有引入回歸。
- [x] **12.2** ~~`orchestrator.handle_user_query()` 的 `ws_broadcaster` 參數~~——已由總架構師
  直接修正並驗證（`pytest tests/ -q` 102 passed），對應 `2026-07-28_架構圖合規性複查與待辦.md`
  §2.2。這項不需要 Kiro 動手，列在這裡只是留紀錄；Kiro 檢查到這裡可以直接跳過，回報時
  註明「總架構師已處理」即可。

### Phase 13：純程式碼工作（Kiro 可以直接做完，不需要等我們先做任何 AWS 設定）

> **排序原則（2026-07-28重新設計）**：這個 Phase 只放「Kiro 自己就能寫完、寫完就能跑
> `pytest` 驗證，完全不需要等團隊先開通 AWS 憑證/建 S3 bucket/建 Bedrock KB」的項目。
> 需要我們先做 AWS Console 操作、或者程式寫完後需要我們拿真實 AWS 環境驗證的項目，
> 全部移到 **Phase 14**，依「需要我們做什麼」的先後順序排列，讓團隊一眼就看出下一步
> 該誰動手。**這裡的所有項目風險比 Phase 0-12 高，會動到主線流程或新增檔案，仍然需要
> 總架構師明確指示才開始，不是自動接續 Phase 12 就做。**

- [x] **13.1** `src/agent/a2_tools.py` 的三個 `@tool` 函式（`plan_routes_tool`／
  `calculate_ete_tool`／`evaluate_rules_tool`）。純包裝，計算邏輯不變，只是把
  `GATEWAY.xxx()` 包成 Strands 工具介面。
- [x] **13.2** `src/agent/a2_orchestrator_agent.py` 全部函式（`_build_a2_system_prompt`／
  `create_a2_agent`／`_get_a2_agent`／`decide_and_execute`）。system prompt 的工具呼叫
  條件必須跟 `orchestrator.py::classify_incident()` 現有的判斷邏輯一致，不是重新設計規則。
  **注意**：`_get_a2_agent()` 在沒有 AWS 憑證/Bedrock model access 時應該要能安全回傳
  `None`（比照 `whatif_agent.py::_get_agent()` 的既有慣例），這樣 13.3 才能在沒有真實
  AWS 環境的情況下也跑得動、可以驗證安全網邏輯。
- [x] **13.3** `orchestrator.py::handle_incident()` EXECUTE 階段接上 `decide_and_execute()`，
  **必須**保留安全網（Agent 漏呼叫必要工具、或 Agent 不可用時，直接補呼叫決定性函式）。
  完成後跑 `pytest tests/test_reporting.py tests/test_routing.py tests/test_rules.py -v`
  確認 90/70/41 分鐘等黃金值完全沒有變動——這是這個項目唯一的成功標準，任何一個黃金值
  跑掉都要停下來回報，不能自己調整測試去遷就新結果。**這一步不需要真的 AWS 環境**：
  沒有憑證時 `_get_a2_agent()` 回 `None`、安全網全權接手，golden value 測試走的路徑
  跟現在完全一樣。
- [x] **13.4** `src/reporting.py` 的 `_invoke_bedrock_converse`／`_generate_with_llm`／
  `_generate_notification_with_llm`——**這裡只要求把程式碼寫出來、跑 `python3 -m py_compile`
  跟 `import` 測試過關**，不要求真的呼叫到 Bedrock（那一步移到 Phase 14.3，因為需要真實
  AWS 環境才能驗證）。**注意**：`generate_report()` 跟 `_generate_c1_c3_fallback()` 現在
  都已經多一個 `bundle` 參數（2026-07-28架構複查修正時為了 SOP-5 警力人數計算加的，見
  `2026-07-28_架構圖合規性複查與待辦.md` §8.2），`_invoke_bedrock_converse` 組 prompt 時
  記得把 SOP-5 的警力人數（`count_affected_intersections()` 算出來的數字）也放進 facts
  block，不要漏掉這個已經補上的事實欄位。
- [x] **13.5** `scripts/upload_data_to_s3.py`（鷹架已備好，交還給 Kiro 實作，不由總架構師
  代寫）。TODO：比照 `upload_sop_to_s3.py` 的 boto3 寫法實作 `main()`，缺檔檢查邏輯已經
  寫好（五個檔案都存在時不報錯，並正確在缺少 `S3_DATA_BUCKET` 時提前報錯，這部分不用
  重寫）。**這裡只要求程式碼正確、`python3 -m py_compile` 過關**，不要求真的執行上傳
  （那一步移到 Phase 14.1，需要團隊先建好 S3 bucket）。
- [x] **13.6**（[2026-07-28新增] 命題投影片模組5加分項：多語通報支援中英以外語言）
  `src/reporting.py::_generate_c4_fallback()`（第222行）補上日文／韓文簡訊生成。
  **這項純程式碼、不需要AWS**——保底模板（`USE_BEDROCK=false` 路徑）本來就是固定範本
  翻譯，不是 LLM 即時翻譯，比照現有 `zh`/`en` 兩個範本的寫法，直接用固定的日文／韓文
  範本字串（跟 `en` 版本用一樣的事實欄位：`incident.location`／`incident.type`／
  `route_name`／`ete.minutes`），**不要**去外部呼叫翻譯API或依賴任何AWS服務。
  `Notification` model（`models.py`）已經有 `ja`/`ko` 欄位可以直接填，不用改型別。
  觸發條件維持不變（SOP-6 `multilingual=True` 時才產生，見 `prompts/notification.txt`
  規則5「只在漫遊比率達SOP-6門檻時產出中文以外的語言版本」——現在的邏輯應該是
  達門檻時中英日韓四語都出，不是只出中英兩語）。`_generate_notification_with_llm()`
  （真Bedrock路徑，Phase 13.4已完成）如果也只有中英，一併補上，兩條路徑要一致。
  完成後補 `tests/test_reporting.py` 對應測試（比照現有
  `test_c4_sop6_triggered_en_is_not_none` 的寫法，斷言 `ja`/`ko` 也非空）。
- [ ] **13.7**（[2026-07-28新增] 對應 `2026-07-28_架構圖合規性複查與待辦.md` §2.3，
  中風險，demo有加分價值——現在Phase13已經把A2 Agent真的接上，這個事件能讓評審看到
  「Agent正在一步步決定要呼叫哪個工具」，呼應「LLM決定要call哪個工具」的賣點，不是
  純粹補齊而已）`decision.task_update.v1`（Agent活動面板逐任務即時更新）。
  **設計方向（不要重新設計，照這個做）**：
  1. `orchestrator.py::handle_incident()` 簽章加一個可選參數
     `ws_broadcaster=None`（跟 `handle_user_query()` 已有的 `ws_broadcaster` 參數同一個
     模式，比照抄）。
  2. **不要**嘗試從 Strands Agent 內部攔截逐步工具呼叫（`_extract_results()` 已經證明
     這個介面不穩定、猜不準，見 Phase 14.3 的殘留風險註記）。改成在 EXECUTE 階段的
     既有步驟（路網規劃前後、ETE計算前後、報告生成前後）各自呼叫一次
     `ws_broadcaster`，payload 帶 `{trace_id, dispatch_seq, status}`（`status` 例如
     `"routing_started"`／`"routing_done"`／`"ete_started"`／`"ete_done"`／
     `"report_started"`／`"report_done"`），`dispatch_seq` 用簡單遞增整數即可。
  3. `ws_broadcaster` 是 async function，但 `handle_incident()` 本身是同步函式——比照
     `src/agent/loading.py::broadcast_loading_start_sync()` 的寫法（用
     `asyncio.get_event_loop()` 判斷是否在運行中的 loop 裡，`ensure_future` 或
     `run_until_complete` 二選一），不要自己重新設計同步轉非同步的機制。
  4. `main.py::evaluate_incident()` 呼叫 `orchestrator.handle_incident(incident,
     ws_broadcaster=ws_manager.broadcast)`。
  5. `frontend/js/ws.js` 已經有 `case "decision.task_update.v1"` 分支（呼叫
     `appendActivityEntry("task_update", payload)`），前端不用改。
- [ ] **13.8**（[2026-07-28新增] 低優先度，`2026-07-28_架構圖合規性複查與待辦.md` §2.3，
  單人demo用不太到，時間真的很夠再做）`rules.evaluated.v1`——在
  `main.py::_periodic_rule_monitor()`（Phase 12.1）跟 `handle_trigger_batch()` 呼叫
  `evaluate_rules` 之後，額外推播一次 `{"message_type": "rules.evaluated.v1", "payload":
  {...SensingResult序列化...}}`，讓F1圖表在每次規則評估後都能更新，不限於決策週期完成。
  `frontend/js/ws.js` 已有 `case "rules.evaluated.v1"` 分支（呼叫 `onRulesEvaluated`），
  但 `onRulesEvaluated()` 目前是空函式（`app.js` 裡只有註解「可選：更新圖表或KPI」），
  補這項時記得順便把 `onRulesEvaluated()` 的內容也寫出來，不然推播了前端還是沒反應。
- [ ] **13.9**（[2026-07-28新增] 低優先度，`2026-07-28_架構圖合規性複查與待辦.md` §2.3，
  單人demo用不到，時間真的很夠再做）`chat.response.v1`／`chat.input_lock.v1`／
  `chat.system_status.v1`——這三個是「多分頁/多人同時看同一對話」情境的冗餘推播管道，
  `sendMessage()` 已經用同步REST處理完整流程，單人操作看不出差異。如果要做：
  `chat.response.v1` 在 `process_whatif_request()` 回傳前多推播一次（帶
  `correlation_id`，前端 `ws.js` 已經有用 `correlation_id` 去重的邏輯，不會重複顯示）；
  `chat.input_lock.v1`／`chat.system_status.v1` 目前沒有明確的觸發時機設計，若要做需要
  先回來跟總架構師確認觸發條件，不要自己發明。

### Phase 14：需要我們先做 AWS/手動操作，或程式做完後需要我們驗證的部分

> **排序原則**：依「需要我們做什麼」的先後順序排——先做的是後面步驟的前提。每一項都需要
> 總架構師/團隊明確指示才開始，Kiro 不主動處理這個 Phase 底下任何一項。

- [ ] **14.1**（需要我們：申請/設定 AWS 憑證 + 建立 S3 bucket）設定好 `S3_DATA_BUCKET`
  環境變數與 AWS 憑證後，實際跑 `python3 scripts/upload_sop_to_s3.py`（Phase 13.1 已完成的
  程式碼，見 §2.4）跟 `python3 scripts/upload_data_to_s3.py`（Phase 13.5 完成後），確認
  S3 上真的出現 7 個 SOP txt 檔 + 5 個原始資料檔。
- [ ] **14.2**（需要我們：AWS Console 手動操作，依賴 14.1 完成）在 Bedrock 頁面用 14.1
  上傳的 SOP 索引檔建立 Knowledge Base（向量儲存選 S3 Vectors），觸發 Sync，取得 KB ID
  填入 `BEDROCK_KNOWLEDGE_BASE_ID` 環境變數。完成後可以請我幫忙驗證：跑
  `query_sop("路面塌陷該怎麼處理")` 之類的問題，確認 `retrieval_source` 真的是
  `"bedrock"` 而不是掉進 `local_fallback`。對應 `2026-07-28_架構圖合規性複查與待辦.md`
  §2.4——AWS 部署分層圖把這項標為核心必做，但一直沒有真的執行，目前 SOP 檢索永遠走
  `bedrock_service/local_fallback.py` 保底路徑。
- [ ] **14.3**（需要我們：開通 AWS Bedrock model access，依賴 13.4 完成）用
  `USE_BEDROCK=true` 實際跑一次三筆黃金事件，確認 Phase 13.4 寫的
  `_invoke_bedrock_converse` 等函式真的能打到 Bedrock、生成的建議書/簡訊有引用到正確的
  事實數字（結構性斷言：ETE分鐘數、路段名稱、SOP條款編號、SOP-5警力人數都要出現在生成
  文字裡，不要求逐字比對，因為 LLM 輸出本來就不是100%決定性可重現）。
  **[2026-07-28新增驗證項]**：同時要驗證 `a2_orchestrator_agent.py::_extract_results()`
  對真實 Strands `raw_response` 的解析邏輯是否正確——這段程式碼假設
  `raw_response.messages[].tool_use[].name`／`.result` 這個形狀，從寫出來到現在都沒有
  真實 AWS 環境可以驗證過。確認方法：跑一次 ACC_001（`requires_rerouting=True`），檢查
  log 裡 `A2 Agent 規劃完成` 那行有沒有出現、`orchestrator.py` 裡
  `a2_result.get("route_plan")` 是否真的抓到非空值（可以暫時加一行 debug log 確認，
  驗證完再拿掉）。如果解析邏輯是錯的（例如 Strands 實際回傳的屬性名稱不是
  `messages`/`tool_use`），要回頭修 `_extract_results()`，不能因為安全網會兜底、
  黃金值不會壞掉就放著不管——那樣 A2 的「LLM決定」永遠是擺設，沒有真正達成
  `2026-07-28_架構圖合規性複查與待辦.md` §2.5 想解決的問題。
- [ ] **14.4**（不強制，需要我們：AWS Console 建立 Guardrail，依賴 14.3 完成。Eric的
  `CityNexus_AWS技術選型.md`筆記建議「如果時間允許優先做這個，會是評審在意的可信度
  亮點」）Bedrock Guardrails（防LLM竄改SOP條款/數字）。**現況**：目前完全靠
  `prompts/report.txt`（「只能使用提供的事實資料，不得添加、推測或改寫任何數字」）+
  事實欄位一律由決定性 Python 計算注入這兩層做到「LLM不得竄改事實」，**功能上已經足夠**，這項是錦上添花，不影響
  核心 Demo 正確性。TODO(Kiro，需總架構師指示才開始)：需要先在 AWS Console 建立
  Guardrail 並取得 ID（手動操作，不是純程式碼），再掛進 `_invoke_bedrock_converse()`。
- [ ] **14.5**（需要我們：手動 CLI 互動，不依賴其他 14.x 項目，隨時可以獨立做）
  `../agentcore-runtime-deploy/`（AgentCore Runtime 部署）。`entrypoint.py` 已經修過一個
  會導致每次呼叫都炸 `TypeError` 的 bug（見該資料夾 README 與
  `2026-07-28_架構圖合規性複查與待辦.md` §六），程式碼已就緒，只差團隊實際跑
  `agentcore create`／`agentcore dev`／`agentcore deploy`／`agentcore invoke` 這幾個
  需要真實 AWS 帳號互動的指令。部署失敗、逾時、或 Demo 現場網路不穩，直接不展示這個
  加分項即可，`main.py` 核心流程完全不受影響。

---

## 三、遇到下列情況必須立刻停下來回報，不能自己決定

- 某個 spec 文件的內容跟另一份矛盾（即使看起來很小）。
- 某個 `[INFERRED]`/`[待確認]` 標記的欄位，實作到發現形狀真的不夠用。
- 需要新增 `pyproject.toml` 沒列出的套件依賴。
- 需要新增 `00-tech-stack.md` §3 固定目錄結構沒列出的檔案或資料夾。
- 任何一項驗收測試改了三次還是過不了。
