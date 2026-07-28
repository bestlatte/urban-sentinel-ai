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

- [ ] **0.1** 覆核 `src/models.py`：對照 `.kiro/steering/02-data-contract.md`、各模組 spec，確認沒有 `[INFERRED]` 標記的欄位跟你即將要寫的邏輯對不上；跑 `pytest tests/test_models.py` 確認 4 條全過。
- [ ] **0.2** [待確認] `EvidenceRef`、`differences_from_base`、`KpiSummary` 三處標了 `[INFERRED]` 的欄位——如果實作到對應功能時發現形狀不對，回報並提出修改建議，不要私自改了就繼續。

### Phase 1：M1 資料感知與規則（零外部依賴的純函式）

- [ ] **1.1** `src/loaders.py`（D1-D4）+ `tests/test_loaders.py`。Spec：`.kiro/specs/m1-data-ingestion/requirements.md` 全文。特別注意真實 CSV 的 `%` 字串解析（測試#1/#2）。
- [ ] **1.2** `src/rules.py`（P1-P5）+ `tests/test_rules.py`。同一份 spec。特別注意 SOP-1 全15路段分級 vs 城市應變觸發限定2段的區分（測試#6/#6b 都要留著）。

### Phase 2：M2 路網規劃（純函式，依賴 Phase 1 的型別但不依賴其實作）

- [ ] **2.1** `src/routing.py` 的 `plan_route()`（R1-R5）+ `tests/test_routing.py`。Spec：`.kiro/specs/m2-incident-routing/模組2C_本機路網重規劃引擎_第一階段Spec.md` 第4-6節。九種 `ReasonCode` 用 `SPEC-00` §3.3 的命名。
- [ ] **2.2** `src/routing.py` 的 `count_affected_intersections()`（`COUNT_INTERSECTIONS`）。同一份 spec 檔頭補註。

### Phase 3：M4 ETE 與報告生成

- [ ] **3.1** `src/reporting.py` 的 `calculate_ete()` + 對應測試。Spec：`.kiro/specs/m4-decision-reporting/requirements.md` 第二節。三筆黃金值（90/70/41分）精確斷言。
- [ ] **3.2** `src/reporting.py` 的 `generate_report()`（C1-C4）+ 對應測試。同一份 spec 第三節；提示詞讀 `prompts/report.txt` + `prompts/notification.txt`，不要硬編在程式碼裡。

### Phase 4：M3 子套件（本機優先，雲端疊加）

- [ ] **4.1** `src/bedrock_service/sop_data.py`（SOP JSON 預載）。Spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第六節。
- [ ] **4.2** `src/bedrock_service/local_fallback.py`（本機關鍵字比對，`KEYWORD_MAP` 已經是完整資料，只需實作比對函式）+ `tests/test_sop_retriever.py` 的本機部分。同一份 spec 第四節。
- [ ] **4.3** `src/bedrock_service/bedrock_kb.py`（雲端呼叫）。同一份 spec 第三節。**需要 AWS Bedrock model access 已開通**，未開通前可以先跳過，不影響 4.4。
- [ ] **4.4** `src/bedrock_service/sop_retriever.py`（`query_sop()` 主邏輯 + 模式切換，含 `try/except` 真的退化）+ 補完 `tests/test_sop_retriever.py` 剩餘測試。同一份 spec 第五節。
- [ ] **4.5** `src/session/models.py` 覆核（已是完整 dataclass，不太需要改動）。
- [ ] **4.6** `src/session/session_manager.py`（`handle_message`/`record_response`/`clear_session`）+ `tests/test_session_manager.py`。Spec：`.kiro/specs/m3-bedrock-advisor/W2-session-manager/design.md`。

### Phase 5：解釋鏈記錄與生成層

- [ ] **5.1** `src/decision_trace.py` 的 `open_trace()`/`record_step()`。Spec：`.kiro/specs/m4-explanation-chain-and-orchestrator/SPEC-M4A_解釋鏈_記錄層.md` 第4節，含全部十項驗收測試。
- [ ] **5.2** `src/decision_trace.py` 的 `resolve_segment_id()`/`generate_report_explanation()`/`answer_trace_query()`。Spec：`SPEC-M4B_解釋鏈_生成層.md`。

### Phase 6：What-if 覆寫重算引擎（依賴 Phase 1-3 的純函式都已完成）

- [ ] **6.1** `src/whatif_engine.py` 的 `apply_scenario_overrides()`。[待確認] entity 前綴（`BS_`/`RD_`）對應到 bundle 哪個欄位的完整映射表，目前只有原型邏輯，需要跟 `.kiro/steering/02-data-contract.md` §2-3 的欄位表逐一核對。
- [ ] **6.2** `src/whatif_engine.py` 的 `run_scenario()` 覆核——確認呼叫的是 `gateway.evaluate_rules()`/`gateway.plan_routes()`/`gateway.calculate_ete()`（透過 Gateway），不是直接 import Phase 1-3 的函式。

### Phase 7：W1 Agent（依賴 Phase 4 的 K3、Phase 6 的 whatif_engine）

- [ ] **7.1** 確認 `src/agent/system_prompt.py` 能正確讀到 `prompts/advisor.txt`（已是完整實作，跑一次 import 驗證即可）。
- [ ] **7.2** `src/agent/loading.py` 的 loading 步驟推播邏輯（方案B兩段式，見 design.md 第十一節）。
- [ ] **7.3** `src/agent/tools.py` 的 `query_sop`（已接好 `bedrock_service`，覆核即可）。
- [ ] **7.4** `src/agent/tools.py` 的 `_get_current_context()`。[待確認] 目前作用中的 incident/bundle 從哪裡取得——這是唯一還沒定案的整合點，需要跟 `orchestrator.py` 的 `GlobalState`（Phase 8）對過介面後才能定案，建議 Phase 8 做完後回頭補這一項。
- [ ] **7.5** `src/agent/response_formatter.py` 的 `format_response()`。Spec：`W1-whatif-agent/design.md` 第七、八節。
- [ ] **7.6** `src/agent/whatif_agent.py` 全部函式（`create_whatif_agent`/`_build_prompt`/`process_whatif`/`process_whatif_request`）。同一份 spec 第五、六、十節。**需要 Strands SDK 已安裝、Bedrock model access 已開通**。

### Phase 8：Orchestrator（依賴前面全部模組）

- [ ] **8.1** `src/orchestrator.py` 的 `StubGateway` 全部方法（假資料，不讀 `data/**`）。Spec：`m5-api-orchestrator-dashboard/design.md` 第2節。
- [ ] **8.2** `src/orchestrator.py` 的 `LiveGateway` 全部方法（串接 Phase 1-4 的真實模組）。同一份 spec。
- [ ] **8.3** `src/orchestrator.py` 的 `classify_incident()`（A1）。已對照真實SOP文字確認過對照表，直接照 docstring 實作即可，不需要重新設計。
- [ ] **8.4** `src/orchestrator.py` 的 `handle_trigger_batch()`（規則觸發靜態分派表）。Spec：`SPEC-O2` §2。
- [ ] **8.5** `src/orchestrator.py` 的 `handle_incident()`（七階段生命週期）。Spec：`SPEC-O1` 全文 + `SPEC-O2` §3（事件注入LLM規劃器）。
- [ ] **8.6** `src/orchestrator.py` 的 `get_global_state()`/`reset()`。Spec：`SPEC-O1` §3 GlobalState。做完這項後回頭補 7.4。
- [ ] **8.7** 覆核 `handle_user_query()`（三分支路由邏輯已經是完整實作，這裡只需確認跟 Phase 7 的 W1、Phase 5 的 M4B 接得起來）。

### Phase 9：外殼（依賴前面全部模組）

- [ ] **9.1** `src/ws_manager.py` 的 `ConnectionManager` 全部方法。
- [ ] **9.2** `main.py` 的 `GET /api/dashboard`。
- [ ] **9.3** `main.py` 的 `POST /api/incidents/evaluate`。
- [ ] **9.4** `main.py` 的 `POST /api/what-if`（三分支回應形狀，見 `.kiro/steering/04-system-architecture.md` §5）。
- [ ] **9.5** `main.py` 的 `GET /api/health`。
- [ ] **9.6** `main.py` 的 `unified_exception_handler` 內容（骨架已掛上，補完錯誤碼映射邏輯）。
- [ ] **9.7** `main.py` 的 7 個 WebSocket 廣播時機接入 `orchestrator.py`／`ws_manager.py`（見 `04-system-architecture.md` §5 總表）。

### Phase 10：前端（後端資料形狀穩定後才做，由小到大：工具函式→狀態→渲染→頁面組裝）

- [ ] **10.1** `frontend/css/*.css` 全部 6 個檔案（`chat-variables.css` 已完整，其餘覆核並補完）。
- [ ] **10.2** `frontend/js/chat-utils.js`（`escapeHtml`/`formatTime`）。
- [ ] **10.3** `frontend/js/chat-state.js`（`ChatState` + 收合/拖拉，design.md 已有完整程式碼可抄）。
- [ ] **10.4** `frontend/js/chat-render.js`（渲染函式，design.md 已有完整程式碼可抄，注意B級用橘色不是黃色）。
- [ ] **10.5** `frontend/js/api.js`（Fetch 四端點）。
- [ ] **10.6** `frontend/js/ws.js`（連線 + message_type 分派）。
- [ ] **10.7** `frontend/js/chat-app.js`（`sendMessage()` 呼叫 REST，不是WS）。
- [ ] **10.8** `frontend/js/charts.js`。
- [ ] **10.9** `frontend/js/map.js`。
- [ ] **10.10** `frontend/js/app.js`（KPI/F7分頁/F2彈窗/F5報告卡片，[待確認]項目見 `index.html` 內補註的業界通用版原型，可依團隊意見調整版面但資料形狀不能變）。
- [ ] **10.11** `frontend/index.html` 最終走查——所有 `<script>`/`<link>` 路徑正確、六分區+F6面板都對應到已完成的JS函式。
- [ ] **10.12** 手動下載 Chart.js 放進 `frontend/vendor/`（見該資料夾 README）。

### Phase 11：整合驗證（不寫新程式碼，是驗收關卡）

- [ ] **11.1** `USE_STUB_MODULES=true` 跑 `uvicorn main:app --reload`，確認四端點回應通過契約驗證、前端六分區以假資料完整顯示。
- [ ] **11.2** `USE_STUB_MODULES=false`（真實模組）跑三筆黃金事件（ACC_001/EVT_002/EVT_003），逐項比對 `.kiro/steering/04-system-architecture.md` §8 黃金驗收表。
- [ ] **11.3** `USE_BEDROCK=false` 保底模式重跑三筆事件，確認完整流程不中斷。
- [ ] **11.4** 全部 `tests/` 通過（`pytest tests/ -v`），確認沒有殘留的 `pytest.skip`。

### Phase 12：加分項（核心全部完成、Demo 排練過一次之後才做）

- [ ] **12.1** `scripts/generate_sop_index_files.py` + `scripts/upload_sop_to_s3.py`（K3雲端索引建置）。
- [ ] **12.2** Bedrock Knowledge Base 建立（AWS Console 手動操作）。
- [ ] **12.3** `../agentcore-runtime-deploy/`（AgentCore Runtime 部署，見該資料夾 README，`agentcore create`/`deploy` 需要手動 CLI 互動）。

---

## 三、遇到下列情況必須立刻停下來回報，不能自己決定

- 某個 spec 文件的內容跟另一份矛盾（即使看起來很小）。
- 某個 `[INFERRED]`/`[待確認]` 標記的欄位，實作到發現形狀真的不夠用。
- 需要新增 `pyproject.toml` 沒列出的套件依賴。
- 需要新增 `00-tech-stack.md` §3 固定目錄結構沒列出的檔案或資料夾。
- 任何一項驗收測試改了三次還是過不了。
