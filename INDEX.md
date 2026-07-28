# 專案骨架索引

本資料夾是依照 `.kiro/steering/00-tech-stack.md` 規定的固定目錄結構整理出來的乾淨版本，把團隊 Drive 下載內容（`../drive-download-20260728T020949Z-1-001/`，保留作為原始備份，不要刪除）依照 Kiro 慣例（`.kiro/steering/`、`.kiro/specs/`）重新歸位。

`../agentcore-runtime-deploy/`（`project/` 的同層資料夾，不在 `project/` 內部）是 AgentCore Runtime 加分項的獨立部署骨架，故意放在外面避免 `agentcore create` 產生的官方骨架跟本專案固定目錄結構混在一起，見該資料夾 README.md。

---

## ✅ 已解決：以業界架構師視角複查，抓到 3 處「文件說有、程式碼沒接上」的結構性落差

搭完鷹架後不是看檔案齊不齊，而是重新檢查「架構圖上畫的依賴關係，程式碼裡是不是真的接了線」，抓到三個問題：

1. **`ModuleGateway`（Stub/Live 切換機制）定義了但沒人用**：`orchestrator.py` 的 `handle_trigger_batch`／`handle_incident`／`classify_incident` 完全沒有透過 `GATEWAY` 存取 M1/M2/M4，等於白定義了這套「開發期間先用假資料、之後換真實模組不用改呼叫端」的機制。`src/whatif_engine.py` 也是直接 `from src.rules import evaluate_rules` 繞過去。已修正：這些函式與 `whatif_engine.run_scenario()` 全部改成透過 `GATEWAY.xxx()` 存取，並回頭同步修正 `W1-whatif-agent/design.md` 的對應說明。
2. **`main.py` 建的 `GATEWAY` 是它自己的區域變數，`orchestrator.py` 模組層級的 `GATEWAY` 其實永遠是 `None`**——兩個不同名字空間，`orchestrator.py` 的函式讀不到 `main.py` 建好的實例。已改成 `orchestrator.GATEWAY = orchestrator.build_gateway()`，直接賦值進模組本身，避免兩份實例。已用 `python3 -c "import main; print(main.orchestrator.GATEWAY)"` 實際跑過驗證，確認現在真的是同一個物件、路由也都正確註冊（4個REST+`/ws`，沒有多餘端點）。
3. **`m5-api-orchestrator-dashboard/design.md` 提到的「三個Envelope端點共用一個FastAPI例外處理器」，鷹架第一版沒有真的接上**——已在 `main.py` 補上 `unified_exception_handler`，把例外收斂成 `status="error"` 的 Envelope（內容邏輯留 TODO，但骨架已經掛上，Kiro 不會漏掉這一步）。

這三個問題的共通點是：**單看每個檔案都「看起來合理」，但沒有實際 import 一次、跑一次，看不出接線斷在哪**——這是這次以「架構師視角」複查才抓到的，也是之後每次鷹架後都該做的驗證方式，不能只憑檔案清單判斷完整性。

---

## ✅ 已解決：搭鷹架時盤點出的 5 個架構空白，已補上業界通用版原型（供團隊雕琢，非最終定案）

鷹架搭完後，以總架構師視角重新檢視，發現 5 個從沒被任何 spec 決定過的空白。依指示先做出合理原型，讓團隊有東西可以雕琢，而不是留白等決定：

1. **「Agent活動面板」沒有畫面歸屬**——`SPEC-O3` 定義的 `decision.cycle_start.v1`／`decision.task_update.v1` 找不到接收畫面（M5 六分區版面圖裡沒有這個面板）。**決定**：併入 F7（決策依據面板）當「即時活動」分頁，跟原本的「決策依據」分頁並列——兩者都是「決策過程的即時可解釋性」，呼應 SPEC-M4B「記錄與生成分離」的精神。已寫進 `frontend/index.html`（`#f7-activity-feed` 分頁）與 `frontend/js/app.js`（`appendActivityEntry()`）。
2. **F1/F2/F3/F4/F5/F7 只有一句話描述，沒有像 F6 的元件拆解**——已在 `frontend/index.html` 補上具體 DOM 結構與各區塊該接哪個 payload 欄位的註解，`app.js` 補上對應的渲染函式簽章（`renderKpis`／`renderDecisionBasis`／`renderReportCard`／`showAlertModal`）。
3. **5 張 KPI 卡片內容從沒定義過**——依「維運Dashboard黃金指標」慣例（現況/告警/健康度/覆蓋率/系統模式）定義：進行中事件數、目前最高應變等級、全路網平均飽和度、SOP-6觸發站點數、系統模式(live/degraded)。已寫進 `src/models.py` 的 `KpiSummary`。
4. **M4B 函式沒有掛到任何檔案**——`open_trace`／`record_step`／`generate_report_explanation`／`answer_trace_query`／`resolve_segment_id` 之前只在文件裡被提及、沒有實際歸屬檔案。已新增 `src/decision_trace.py`（單一職責分離，理由跟 K3/W1/W2 拆成獨立套件一致），`orchestrator.py` 的 `handle_user_query()` 也已經真的 import 並呼叫它（三分支路由邏輯本身已經是可運作的實作，不是 stub）。
5. **`simulate_scenario` 沒有真正的重算介面**——新增 `src/whatif_engine.py`：深拷貝 bundle 套用 `ScenarioOverrides`，重用既有的 `evaluate_rules`／`plan_route`／`calculate_ete`（不另開一套「_with_overrides」版本，維持純函式單一職責）。`agent/tools.py` 的 `simulate_scenario` 已接上這個引擎；仍有一個更小的待確認點：目前作用中的 incident/bundle 從哪裡取得（`_get_current_context()` 留 TODO）。

搭鷹架過程中順手抓到並修正了 2 處自己引入的不一致：`routing.py` 的 `plan_route()` 簽章原本跟 `orchestrator.py` 的 `ModuleGateway.plan_routes(request)` 對不上（三參數 vs 單一物件），以及 `m2-incident-routing/模組2B` 補註裡又是第三種簽章寫法——已統一成 `plan_route(request: RouteRequest) -> RoutePlan`。

---

## 目錄結構

```
project/
├─ .kiro/
│  ├─ steering/                              ← 全隊鐵律，Kiro 每次生成都會讀
│  │  ├─ 00-tech-stack.md                    技術棧、目錄結構、API表面、禁用清單
│  │  ├─ 01-module-boundaries.md             五模組所有權、決策職責三層
│  │  ├─ 02-data-contract.md                 資料正規化、SOP門檻、ETE公式、黃金驗收值
│  │  ├─ 03-testing-and-ai-collaboration.md  測試策略(驗收測試→assert)、docstring規範、Kiro協作原則 ★總架構師補寫
│  │  └─ 04-system-architecture.md           ★總架構師補寫，Kiro第一份必讀：全系統一頁式總覽、資料流程圖、完整message_type總表、DecisionResult最終型別
│  └─ specs/
│     ├─ m1-data-ingestion/                  模組1：資料感知與規則（D1-D4、P1-P5）★總架構師補寫
│     ├─ m2-incident-routing/                模組2：事件與路網規劃（R1-R5）
│     ├─ m3-bedrock-advisor/                 模組3：Agent、RAG 與 What-if
│     │  ├─ K3-sop-rag/
│     │  ├─ W1-whatif-agent/
│     │  ├─ W2-session-manager/
│     │  └─ F6-chat-ui/
│     ├─ m4-explanation-chain-and-orchestrator/  解釋鏈(M4A/M4B) + Orchestrator核心邏輯(O1-O3)
│     ├─ m4-decision-reporting/              官方M4：ETE計算 + C1-C4建議書/簡訊 ★總架構師補寫
│     ├─ m5-api-orchestrator-dashboard/      M5：API外殼/WebSocket/models.py/前端（Orchestrator內部邏輯已讓位給m4-explanation-chain-and-orchestrator）
│     └─ architecture-reference/             整體架構圖與情境說明（背景參考，非規格本身）
│        ├─ 加分項_AgentCore_Runtime部署.md   ★總架構師補寫，P1加分項，見下方「階段7」
│        └─ AgentCore_Runtime_部署參考教學.md CLI操作參考（AWS官方客服機器人範例，程式內容需替換）
├─ data/                                     五個 canonical 資料檔（已换成真實資料，見下方）
├─ src/                                      ★總架構師已鷹架：models.py完整實作，其餘為函式簽章+docstring+TODO(指向對應spec)
├─ frontend/                                 ★總架構師已鷹架：六分區骨架+F6面板DOM，CSS/JS為結構+TODO
├─ contracts/module_exchange_contract.json   ★總架構師已鷹架：列舉值已填，型別細節待從models.py產生
├─ prompts/                                  ★總架構師已鷹架：advisor.txt/report.txt/notification.txt 內容完整（非邏輯，直接抄spec定案文字）
├─ tests/                                    ★總架構師已鷹架：8個測試檔，test_models.py為真實可跑測試，其餘為skip stub+驗收測試編號對照
├─ scripts/                                  ★總架構師已鷹架：K3索引產生腳本、F6 mock server（開發輔助，非交付物）
└─ data_manifest.md / pyproject.toml / .env.example   ★總架構師已鷹架，內容完整
```

---

## 各模組 → 應產出檔案對照（依 `01-module-boundaries.md`，已補齊）

| Spec 資料夾 | 契約模組代碼 | 應寫入的檔案 |
|---|---|---|
| `m1-data-ingestion/` | `data_ingestion`／`sensing_rules` | `src/loaders.py`、`src/rules.py`、`data_manifest.md` |
| `m2-incident-routing/` | `incident_routing` | `src/routing.py`、`data/display_geometry.json` |
| `m3-bedrock-advisor/` | `bedrock_advisor` | `src/agent.py`、`src/bedrock_service.py`、`src/session/`（W2）、`prompts/*` |
| `m4-decision-reporting/` | `decision_reporting` | `src/reporting.py`（A3 ETE + C1-C4） |
| `m5-api-orchestrator-dashboard/` | `api_orchestrator`／`dashboard` | `main.py`、`src/models.py`、`src/ws_manager.py`、`frontend/**`（`orchestrator.py` 邏輯讓位，見下） |
| `m4-explanation-chain-and-orchestrator/` | 見下方說明 | `src/orchestrator.py`（核心邏輯權威） |

---

## ✅ 已決議：`m4-explanation-chain-and-orchestrator/` 為 Orchestrator 邏輯權威版本

`m4-explanation-chain-and-orchestrator/`（`SPEC-00` 共同基礎、`SPEC-M4A` 解釋鏈記錄層、`SPEC-M4B` 解釋生成層、`SPEC-O1/O2/O3` Orchestrator 生命週期／分派編排／對外介面）跟 `m5-api-orchestrator-dashboard/requirements.md` 對 A1事件分類、A2編排、A4決策留痕的定義原本重疊。

**決議（依蔡晟郁指示）：以我們（蔡晟郁＋何明哲）的 `m4-explanation-chain-and-orchestrator/` 為準。**

實際分工邊界：
- **`m4-explanation-chain-and-orchestrator/`** → 提供 `src/orchestrator.py` 的**核心邏輯權威**：A1 分類、A2 分派/編排（SPEC-O2 折衷制）、週期生命週期（SPEC-O1）、A4 決策留痕（SPEC-M4A）、解釋生成（SPEC-M4B）
- **`m5-api-orchestrator-dashboard/`** → 縮小範圍為**外殼**：`main.py`（FastAPI 四端點掛載）、`src/ws_manager.py`（WebSocket 連線管理）、`src/models.py`（共用型別，仍是全專案唯一定義處）、`frontend/**`。凡與 `m4-explanation-chain-and-orchestrator/` 衝突的 Orchestrator 內部邏輯敘述，**以後者為準**，M5 規格中對應段落視為過時。

生成 `src/orchestrator.py` 時，優先餵 `m4-explanation-chain-and-orchestrator/` 全部 6 份文件；`m5-api-orchestrator-dashboard/` 僅用於 `main.py` / `ws_manager.py` / `models.py` / `frontend/` 部分。

---

## ✅ 已補齊：模組1（資料感知與規則）與官方模組四（ETE/報告生成）

團隊 Drive 原本完全沒有這兩塊的規格，已由總架構師依 `01-module-boundaries.md`、`02-data-contract.md` 補寫完成：

- **`m1-data-ingestion/requirements.md`**：D1-D4 五資料源載入與正規化（含真實 `signaling_crowd_density.csv` 的 `%` 字串解析規則）、P1-P5 感知計算與 SOP 規則引擎。
- **`m4-decision-reporting/requirements.md`**：A3 ETE 公式計算、C1-C4 建議書/號誌/聯動/簡訊生成，含「LLM 只表達不改寫事實」的具體提示詞契約。

這兩份都是唯讀依據 steering 文件生成，沒有跟其他模組的既有規格衝突。

---

## 資料狀態（已更正）

`data/signaling_crowd_density.csv` 已是黑客松主辦方補齊的**真實資料**（非模擬），取代原本 GPT 生成的版本。已同步更正的黃金驗收值見 `.kiro/specs/m4-explanation-chain-and-orchestrator/SPEC-00_共同基礎.md` 第 5.4 節與 `.kiro/specs/architecture-reference/` 內三份文件——多語通報觸發依據改為 `BS_TPE_101`（0.40）與 `BS_XY_ATT`（0.30），`BS_TPE_DOME` 真實漫遊率僅約 0.05~0.06，不再作為觸發依據。其餘 ETE／路徑篩選黃金值不受影響。

---

## ✅ 已解決：`m2-incident-routing/` Phase 1 沙盒基礎建設與主架構不相容

ling 撰寫的模組2「第一階段獨立版」spec（總覽 + M2-A/B/C/D 四份）為了讓 M2 能不依賴其他模組先獨立開發測試，引入了 SQLite 儲存、7 個 `/api/incidents*` 專屬端點、模組2專屬 WebSocket——這些跟 `00-tech-stack.md` 固定的儲存方式（`data/` JSON + 記憶體）與固定 API 表面（僅4端點+`/ws`，不得擴充）不相容。

**判定**：R1-R5 路網演算法（M2-C）與 A1 分類規則（M2-B）邏輯本身完全正確、跟架構圖一致，問題只在於「開發沙盒」被寫成了「正式交付物」。

**解決**：已在 M2-A/B/D 三份文件與總覽文件加註「Phase 1 → 整合收斂」說明，明確標註 SQLite／專屬端點／專屬WebSocket 僅供獨立開發期間使用，整合進主系統時：
- 儲存改回記憶體物件，不引入 SQLite 依賴
- M2 對外邊界收斂為單一函式呼叫（`process_incident()` / `plan_route()`），由 `orchestrator.py` 呼叫，不透過獨立端點
- 前端資料改走主系統唯一的 `POST /api/incidents/evaluate` 與 `/ws`
- Phase 1 的 4 組 Mock 情境保留下來當單元測試 fixture

---

## ✅ 已解決：`F6-chat-ui/design.md` 三處與主架構不一致

jasminekuosuper 撰寫的 `m3-bedrock-advisor/F6-chat-ui/design.md`（對話視窗前端）核對出三個問題，已直接修正：

1. **殘留舊模擬資料**：`current_data` 範例與 `W1-whatif-agent/requirements.md` REQ-5 都寫著 BL17=31,500人／growth=0.312（GPT 模擬資料殘留），已更正為真實值 31,000人／growth≈0.08，並註明觸發依據是 `User_Count > 25,000` 門檻而非成長率——跟前面在 `02-data-contract.md` 等處修正過的同一批殘留問題同源。
2. **目錄名稱錯誤**：文件多處寫 `static/css/`、`static/js/`，但 `00-tech-stack.md` 固定目錄是 `frontend/`，`main.py` 也只會掛載 `frontend/`。已全部改為 `frontend/`。
3. **WebSocket 訊息未套用共用 Message Envelope**：F6 原本自訂 `{"type": "chat_response", "data": {...}}` 格式，但 `/ws` 是全專案唯一一條連線、F1-F7 共用，`02-data-contract.md` §7 規定所有跨模組訊息都要用同一份 Envelope（`message_type`/`payload` 等固定欄位）分派，F6 自創欄位名會讓前端沒辦法用同一套邏輯處理所有推播。已將第三、五節改為 Envelope 格式（`message_type` 前綴 `chat.*.v1`），並補上 `buildEnvelope()` 輔助函式與 `correlation_id` 追蹤欄位。

R1-R5 以外，F6 的畫面邏輯（Decision Card、Loading、拖拉調整寬度等）本身設計良好，無需更動。

核對 `requirements.md`／`tasks.md` 時再抓到一個小但會影響 Demo 視覺一致性的問題：F6 三份文件都把 B 級狀態色定義成黃色，但 `02-data-contract.md` §8 的權威定義是「A 級紅、B 級橘、正常青綠」，且黃色在 F4 路網圖已經是「次路線」的顏色語意——B 級 banner 用黃色會跟其他面板的顏色語言不一致。已將 `requirements.md`／`design.md` 的 B 級顏色改為橘色；`tasks.md` 因為只是任務拆解、大量沿用未套 Envelope 前的舊寫法，改用一句總註記提示「讀 design.md 的修正版本，不逐字比對」，不用逐行改。

---

## ✅ 已解決：`K3-sop-rag/design.md` 欄位名脫離共用契約 + 保底邏輯沒真的實作

三個問題，已修正：

1. **欄位名不對齊**：`SOPQueryResult` 原本叫 `source`，但 `00-tech-stack.md` §6 保底模式硬性要求規定的欄位名是 `retrieval_source`（其他模組／Envelope `warnings` 靠這個名字判斷是否進入保底模式）。若 K3 自己叫 `source`，跨模組讀不到值，保底狀態永遠標記不出來。已全面改名，並把原本只列兩種值（`bedrock`/`local`）的註解補上第三種 `local_fallback`。
2. **保底行為沒有寫進程式碼**：第八節錯誤處理表格說 Bedrock 呼叫失敗會「自動退化到本機模式」，但第五節的模式切換程式碼完全沒有 `try/except`——照原樣寫，Bedrock 拋例外會讓整個查詢直接崩潰，不會真的退化。已補上例外處理。
3. **檔案結構跟模組所有權對不起來**：第十節寫 `src/rag/`，但 `00-tech-stack.md`／`01-module-boundaries.md` 都把 K3 歸在單一的 `src/bedrock_service.py`。已改為 `src/bedrock_service/` 子套件（內部拆檔案，對外仍是同一個模組名）。`tasks.md` 沿用舊寫法處補了一句總註記提示對應關係。

---

## ✅ 已解決：`W1-whatif-agent/design.md` 進場方向與 SPEC-O3 相反

這是目前核對出來影響最大的一個衝突。W1 原本設計「WebSocket handler 直接呼叫 `process_whatif()`，W1 內部 Agent 自己決定要不要處理」，但 `m4-explanation-chain-and-orchestrator/SPEC-O3` §4 明訂使用者輸入路由是**確定性、零 LLM**，入口是 Orchestrator 的 `handle_user_query()`，判斷問題含前瞻假設詞才轉發給 W1——方向完全相反，而且雙方定義的端點名稱也不同（W1/SPEC-O3 各自寫 `/api/chat`，但 `00-tech-stack.md` 固定的是 `POST /api/what-if`）。

**判定（依你指示「照這個方向改」，以 SPEC-O3 為準）**：已修正 W1 design.md：
- 對外入口統一為 `POST /api/what-if`，由 `orchestrator.handle_user_query()` 呼叫 W1 的處理函式，同步回傳完整結果；WebSocket 只做 loading 進度的額外推播，不當作問題本身的傳輸管道（呼應 `00-tech-stack.md` §4「所有改變狀態的操作走 REST」）。
- W1 內部「LLM 決定要不要呼叫 `query_sop`/`simulate_scenario`」的設計不變，這是收到問題之後的內部邏輯，跟「誰先判斷這是不是 What-if」是兩件事。
- 順手修正三處機械性殘留：`src.rag` → `src.bedrock_service`（K3 改名後的連動）、`source` → `retrieval_source`（K3 改名後的連動）、Bedrock model ID 從硬編碼改為讀 `BEDROCK_MODEL_ID`（跟自己的 tasks.md 本來就衝突）。
- **留一個待整合的缺口，沒有假裝解決**：`simulate_scenario` 工具原本呼叫不存在的 `orchestrator.simulate()`（且會形成 Orchestrator→W1→Orchestrator 循環依賴），已改為直接呼叫 `routing.py` 等決定性模組，但這些模組目前沒有「帶 assumptions 覆寫重算」的公開函式，標記為 TODO，待與模組1/2/4負責人對介面。

同時在 `00-tech-stack.md` §3 補齊了 `src/session/`（W2 用，原本完全沒有定義）與 `agent/`／`bedrock_service/` 可拆成套件的說明，避免同一類「目錄不在固定結構內」的問題在 K3/W1/W2 每份文件各自被抓一次。

`W1-whatif-agent/requirements.md`（早於 SPEC-O3 定案、標記「✅已確認」的原始需求）在呼叫關係上也反映同一個舊理解，已加補註對照到修正版，不重寫歷史記錄本身；REQ-1～8 的行為需求不受影響。`tasks.md` 的 Task 3（`from src.orchestrator import simulate`）與 Task 7（WebSocket handler 直接串 `chat_message`）同樣反映舊架構，已加補註對照，不逐項改寫。W1 三份文件核對完畢。

**後續影響已一併處理**：F6 的 `design.md`／`tasks.md` 原本讓使用者的聊天訊息透過 WebSocket 的 `chat.message.v1` 送出，同樣違反「狀態改變操作走 REST」，已改為 `sendMessage()` 呼叫 `POST /api/what-if`、同步等回應直接渲染；WebSocket 的 `chat.response.v1` 保留為冗餘推播（雙通道保底，用 `correlation_id` 去重避免同一則回覆顯示兩次）。`clear_session` 因為不是決策狀態、只是 W2 session 本地清空，刻意維持走 WebSocket，不算例外遺漏。

---

## ✅ 已解決：`W2-session-manager` session_id 推導方式失效 + 暫存機制脆弱

兩個問題，已修正：

1. **Session ID 的推導基礎被前面的 REST 修正打掉了**：design.md 原本寫「用 WebSocket connection ID 當 session_id」，但聊天訊息已經改走 `POST /api/what-if`（REST，無狀態），沒有「同一條連線」可以推導。已改為：session_id 由前端（F6）頁面載入時產生一次，存在 `ChatState.sessionId`，之後每次 REST 請求都帶著同一個值；`clear_session` 走 WebSocket 時 payload 裡也帶 session_id，不靠 connection 識別。三份文件（design/requirements/tasks）都已補註或修正。
2. **`_pending_message` 暫存設計脆弱**：原本靠 `session._pending_message` 這個可變屬性在 `handle_message()`／`record_response()` 兩次呼叫間傳遞使用者訊息，時序上容易出錯。已改為 `record_response()` 直接收 `user_message` 參數（呼叫端本來就同時握有這個值），移除暫存機制。

---

## ✅ 已解決：`SPEC-O3` 的 `DecisionResult.reports` 跟 `generate_report()` 回傳形狀對不起來

`SPEC-O3` 原本把 `reports.signal_plan`（C2）／`reports.coordination`（C3）定義成獨立的結構化 `object`，但 `m4-decision-reporting/requirements.md` 與 `m5-api-orchestrator-dashboard/design.md` 的 `ModuleGateway.generate_report()` 兩份文件（互相獨立撰寫）都設計成「C1～C3 一次生成、回傳單一建議書全文」，理由是 C2/C3 本來就是 LLM 依 C1 事實生成的文字建議，若要在 orchestrator 層把它們拆回結構化物件，等於要對 LLM 生成的自然語言重新做結構化解析，違反「LLM 只表達事實、不產生事實」原則。

**判定（依你指示「照這個方向改」）**：已修正 `SPEC-O3`——`reports` 只剩 `advisory`（C1+C2+C3 全文）與 `sms`（C4）兩個欄位。同時修正 `m4-decision-reporting/requirements.md` 另一側的形狀不一致：`generate_report()` 原本第二個回傳值寫 `list[Notification]`，但 `SPEC-O3` 的 `sms` 是單一物件 `{zh, en?, ja?, ko?}`，已改成 `tuple[str, Notification | None]`（單一物件）；失敗降級的欄位名也從模糊的「附加欄位」改成明確對齊 `SPEC-O3` 的 `degraded: string[]` 慣例（`"C1_FAILED"`／`"C4_FAILED"`）。

---

## ✅ 已解決：`SPEC-00` §4 全域慣例殘留兩處舊模擬資料格式

跟之前修過的 11 處同一個病根：§4「單位正規化」寫 `Roaming_User_Pct` 是裸數字 `32.0`（舊模擬格式），已更正為真實資料的「帶 % 符號字串」`"40%"` 格式；「模擬資料標示」寫人流資料全為 `Is_Simulated=true`，已更正為真實資料 `provenance="provided"`，不需要 Simulated/Demo 標示。§5.4 的黃金值更正在更早的階段已經做過，這次核對確認沒有回退、其餘章節（命名對照表、ActorCode/ToolName/ReasonCode 列舉、路徑篩選黃金值、飽和例外規則）都跟其他已核對文件一致，無其他問題。

---

## ✅ 已解決：`ReasonCode` 列舉在 SPEC-00 與 M2-C 之間對不起來，會導致執行期崩潰

`SPEC-00` §3.3 的 `ReasonCode` 原本只有 7 值、UPPER_SNAKE_CASE 命名；M2-C（`模組2C_本機路網重規劃引擎`）的 R5 實際產出 9 種原因碼、lower_snake_case 命名，其中 `missing_traffic_snapshot`（找不到車流快照時預設排除）與 `unknown_segment`（alternatives 指向不存在的路段）兩種是 SPEC-00 列舉完全沒有的真實情境。`SPEC-M4A` 的 `record_step()` 對 `reason_code` 做 fail-fast 驗證，遇到列舉外的值會直接拋 `ValueError` 中斷寫入——這是 R1-R5 正常運作路徑上就會發生的情況，不是邊角案例，會讓 demo 卡住。

**判定**：SPEC-00 是列舉唯一來源，已擴充為九值（新增 `UNKNOWN_SEGMENT`、`MISSING_TRAFFIC_SNAPSHOT`）；M2-C 改用跟 SPEC-00 一致的 UPPER_SNAKE_CASE 命名，`saturated_but_retained` 改記錄成 `FindingCode`（不是 `ReasonCode`，因為該候選未被排除）。`SPEC-M4A` 對應的「七值」引用（ExcludedItem 定義、驗收測試#8）已同步改成「九值」。

---

## ✅ 已解決：`SPEC-O1` §5「責任方」欄位易誤導 Kiro 破壞模組解耦

第5節呼叫時序表把「工具/模組執行中 record_step」的責任方寫成「各執行模組（R3/R4/R5/A3/C1...）」，字面上會讓人以為這些模組要自己 import M4A 並呼叫 `record_step`。但核對 `m2-incident-routing`（R1-R5）與 `m4-decision-reporting`（A3/C1-C4）兩份 spec，兩者都設計成完全不知道追蹤機制存在的純函式，這是刻意的解耦設計。已更正為：responsible party 統一是 A2（orchestrator.py），A2 呼叫完這些模組拿到回傳值後代為呼叫 `record_step`；`agent` 欄位只是標示「這步驟的執行者是誰」，不代表呼叫者是誰。其餘章節（trace_id 格式、action 列舉、FIFO 排隊、What-if 不開 trace）跟 SPEC-00/SPEC-M4A 完全對齊，無其他問題。

---

## ✅ 已解決：`SPEC-O2` 靜態分派表誤用「A1」代號 + 「路口計算」沒有歸屬

`SPEC-O2` §2 靜態分派表寫「§5 → [A1路口計算 → C1, C3]」，但 `SPEC-00` 的 `A1` 定義是「事件分類器」，跟「算受影響路口數」是完全不同的功能——重複使用同一個代號。往下追查發現這個「路口計算」小工具**沒有任何 spec 定義它、也沒有指定歸屬**，我自己的 `m4-decision-reporting` spec 只寫了「警力=路口數×2」這個事實敘述，沒說這個數字誰來算——若照原樣實作，很可能被誤植為 LLM 自己心算，直接違反「LLM 不得自行計算數字」的鐵律。

**已修正（四份文件同步）**：
- `SPEC-00` §3.2 新增 `ToolName.COUNT_INTERSECTIONS`，明確不沿用 A1。
- `SPEC-O2` §2/§3.2 改用新代號，不再寫「A1路口計算」。
- `m4-decision-reporting/requirements.md` 補上「`affected_intersection_count`（含 × 2 換算）由呼叫端算好注入」，跟 `ete.minutes` 等其他事實欄位同一套處理方式。
- `m2-incident-routing/模組2C` 補上函式歸屬（`count_affected_intersections()`，需路網拓樸，屬於 `routing.py`），標記為整合期新增、不影響 Phase 1 驗收範圍。

`SPEC-O2` 其餘部分（靜態分派表跟 SOP 條款對應、Phase 平行/序列語意、降級規則、黃金值回歸測試）都跟已核對過的文件一致，無其他問題。

---

## ✅ 已解決：`SPEC-O3` 完整重看抓到三處問題（端點名稱、硬編碼模擬標記、WS事件命名）

上次核對 SPEC-O3 時只針對 `reports` 欄位形狀做了局部修正，這次拿到完整版重新從頭看一遍，抓到三個之前沒觸及到的問題：

1. **端點名稱沒回頭改**：`handle_incident`／`handle_user_query` 原文分別寫 `/api/inject`、`/api/chat`，都不在 `00-tech-stack.md` §4 固定的 4 端點內。`/api/chat` 上次只在 `W1-whatif-agent/design.md` 那邊註記是筆誤，沒有改回 SPEC-O3 本體；`/api/inject` 是這次才發現。已改為 `POST /api/incidents/evaluate`（事件注入）與 `POST /api/what-if`（使用者對話）。
2. **`is_simulated: true` 寫死字面值**：跟本次核對一路修正的「人流資料已是真實資料，不是全部模擬」結論矛盾（驗收測試#8 甚至斷言「恆為 true」）。已改為依實際引用資料的 `provenance` 動態計算。
3. **WebSocket 事件型別是裸字串**：`"alert"`／`"cycle_start"` 等沒有套用 `<domain>.<action>.v<version>` 命名慣例，也沒包 Message Envelope，跟 F6 已經對齊的 `chat.*.v1` 風格不一致。已改用 `decision.<action>.v1`。

---

## ✅ 已解決：`m5-api-orchestrator-dashboard/design.md` 三處問題（含 DecisionResult 命名權威裁定）

1. **`generate_report` 簽章沒同步**：`m4-decision-reporting`/`SPEC-O3` 已改成單一物件 `Notification | None`，這裡還是舊的 `list[Notification]`，已同步修正。
2. **A1 分類表跟 `m2-incident-routing/模組2B` 互相矛盾**：M5 這裡把 `Crowd_Surge_Injury`／`Power_Failure` 的 `requires_rerouting` 寫死 false，M2-B 寫的是條件式（依 `affected_road`/道路ID 是否存在）。**判定**：M5 這張表已被 `Property 10` 正式驗收條件化，作為整合後「要不要呼叫 `plan_routes()`」的權威判斷；`m2-incident-routing` 是 Phase 1 沙盒開發，其條件式判斷屬於簡化版本，整合後以 M5 這表為準。但已加註提醒：**這是簡化取捨、未必是驗證過的 SOP 語意**，Demo 前建議對照 `emergency_traffic_sop.json` 原文再次確認 SOP-3/SOP-5 是否真的完全不需要路網重規劃。
3. **`DecisionResult` 欄位命名跟 `SPEC-O3` 整組對不上**（`control_center_report`/`notifications`/`candidate_evaluations` vs `reports.advisory`/`reports.sms`/無對應欄位）：**裁定 M5 命名為準**——`01-module-boundaries.md` 分工決議已明訂 `src/models.py` 是全專案唯一型別定義處，`SPEC-O3` 只負責編排流程不該重新發明欄位名。已回頭修正 `SPEC-O3`（含其驗收測試）與 `m4-decision-reporting` 的對應引用，補上 `routes.candidate_evaluations`（對應 M2-C 既有的 `candidate_evaluations` 輸出，解決 M5 Property 23 提到但未定義來源的「candidates」）。

至此 `m5-api-orchestrator-dashboard/design.md` 核對完成；`requirements.md`／`tasks.md` 尚未核對。

---

## ✅ 已解決：`m5-api-orchestrator-dashboard/requirements.md` 兩處問題

1. **自己上次改錯欄位名**：核對 M5 design.md 時把 `candidates` 誤改成 `candidate_evaluations` 加進 `SPEC-O3`，這次拿到 requirements.md 才確認 M5 實際用的是 `candidates`（R4.2、R7.6 兩處），已改正回來。
2. **`POST /api/what-if` 的回應形狀在「模擬」跟「回溯追問」兩種情境下沒講清楚**：`SPEC-O3` §4 定義這個端點有三種路由分支（前瞻假設→W1模擬、回溯追問→M4B文字答案、無週期→固定文字），但 M5 的 Requirement 8 只描述了模擬分支，回溯追問的純文字答案沒地方放。**判定**：不新增端點（違反固定API表面），改讓回應的 `message_type` 依分支不同——模擬分支維持 `whatif.evaluated.v1`/`WhatIfResult`；回溯追問與無週期兩種分支改用新增的輕量型別 `TraceAnswer{trace_id, answer_text}`、`message_type="trace.answered.v1"`，不勉強塞進 `WhatIfResult` 的重算欄位。已同步修正 `m5-api-orchestrator-dashboard/requirements.md`（新增 R2.5a、Requirement 1 型別清單、Requirement 8 補註）與 `SPEC-O3` §4。

至此 `m5-api-orchestrator-dashboard/` 三份文件（design/requirements；tasks.md 待核對）核對完成。

---

## ✅ 已解決：`m5-api-orchestrator-dashboard/tasks.md` 缺一個任務（回溯追問分支沒人做）

上一份 requirements.md 核對時新增了 R2.5a（`POST /api/what-if` 的回溯追問／無週期分支，回應型別 `TraceAnswer`），但這份 tasks.md 是在那之前定案的，完全沒有對應的實作任務——只有「前瞻假設」分支（What-if 模擬）被排進 Task 18。如果沒補上，這個分支永遠不會被 Kiro 實作出來。已插入 Task 18a，緊接在 Task 18.4 之後、Task 19 之前。

其餘任務（型別凍結順序、性質測試對應、`candidates` 欄位命名、`generate_report` 簽章）都跟已核對過的 design.md／requirements.md 一致，無其他問題。

---

# 🎉 全部規格文件核對完成

`.kiro/specs/` 底下所有文件（`architecture-reference` 7 份、`m1-data-ingestion`、`m2-incident-routing` 5 份、`m3-bedrock-advisor` 全部 4 個子模組共 12 份、`m4-decision-reporting`、`m4-explanation-chain-and-orchestrator` 6 份、`m5-api-orchestrator-dashboard` 3 份）都已逐一核對完畢，發現並修正的問題已全部記錄在本文件前面各節。可以開始餵給 Kiro，依「🏗️ 建置順序」章節的順序執行。

---

## ✅ 已解決：`00-tech-stack.md` 最終複查，兩處與後續修正同步

整個核對過程做到最後，回頭重看這份最上層 steering 文件，抓到兩處沒跟上後面的修正：

1. **§4 API 表面沒反映 `POST /api/what-if` 雙形狀回應**：核對 `SPEC-O3` 時已確立這個端點依問題類型回傳 `WhatIfResult` 或 `TraceAnswer`，這裡原本只寫 `WhatIfResult`，已補上並指向 `SPEC-O3` §4 的三分支路由規則。
2. **`scripts/` 目錄的例外散落在 F6／K3 兩份 spec 裡各自論證，沒有集中管理**：比照當初 `tests/` 目錄的處理方式，已集中加進 §3 固定目錄結構，說明是一次性開發工具、不隨 `src/` 交付。

---

## ✅ 已解決：`01-module-boundaries.md`（模組邊界規則）三處落後於實際團隊決議

這是全專案最基礎的權威文件之一，核對到最後才發現它從沒跟上前面的決議，問題比想像中根本：

1. **`src/orchestrator.py` 所有權表過時**：第1節表格原本把這個檔案列為「M5獨家」，但團隊早就決議 `orchestrator.py` 的核心邏輯由額外新增的 `m4-explanation-chain-and-orchestrator/`（SPEC-O1/O2/O3）owned，M5 只剩外殼（`main.py`/`ws_manager.py`/`models.py`/`frontend`）——這個決議記錄在 `INDEX.md`，但從沒回頭同步到這份「唯一權威」的 steering 文件。如果 Kiro 只看這份文件、沒看 INDEX.md，會被導向錯誤的 spec。已修正表格並加註完整說明。
2. **M3 owned 檔案漏了 `src/session/`**：`00-tech-stack.md` 已把 `session/`（W2）列進固定目錄歸在 M3 底下，這裡沒同步，已補上。
3. **`模組間資料流通規格.md` 整份缺失，卻被列為衝突處理第2優先**：搜尋整個專案（含 Drive 備份）找不到這份文件——是跟 `五人團隊分工與Spec開發建議書.md` 不同的另一份缺失文件。已加註「實際上跳過此項」，並確認實務上核對時從未真的需要用到它（`02-data-contract.md` 已完整涵蓋其職責），非阻塞。

---

## ✅ 已解決：`02-data-contract.md` 兩處問題（最後一份 steering 文件）

1. **§5 硬性排除原因碼是第三套寫法**：`incident_blocked`／`capacity_below_1000`／`not_direct_intersection` 等，跟 `SPEC-00` 已經統一的 `ReasonCode`（`CLOSED`／`CAPACITY_INSUFFICIENT`／`NOT_DIRECTLY_INTERSECTING`）不只大小寫不同、部分用詞也不同——這是繼 M2-C 之後第二次抓到同一類命名分歧，已統一改用 `SPEC-00` 版本。
2. **§7 「錯誤碼九種」但只列出 8 個**：核對整個專案提到錯誤碼的地方（M5 spec 等）都是同樣這 8 個，判斷是筆誤，已改為「八種」；若之後在機器契約發現真的有第 9 個碼，需回頭補上。

至此全部 4 份 steering 文件都核對完成，`.kiro/` 整包規格全部核對過一輪，沒有遺漏。

---

## ✅ 已對照真實資料與 SOP 原文完成最終驗證

用 `data/city_traffic_flow.json`（112筆）與 `data/emergency_traffic_sop.json`（7 sections 原文）逐一核對整個審查過程引用的數值與公式：

- **三筆事件 ETE 黃金值（90/70/41分）用真實 Saturation_Score 反推公式精確吻合**：ACC_001（`RD_TPE_002` sat=1.0 → 90分）、EVT_002（`RD_TPE_001` sat=1.0 → 70分）、EVT_003（`RD_TPE_007` sat=0.85 → 41分），一分不差。
- **SOP 原文核對出全部門檻值、公式、動作描述都跟 spec 引用一致**（SOP-1 城市應變限定路段、SOP-3 替代站點 `BS_MRT_BL18`、SOP-4 連動 SOP-3、SOP-5 警力公式、SOP-6 門檻、SOP-7 ETE 公式）。
- **解決了 M5 A1 表格 vs M2-B 條件式判斷的懸案**：SOP-3／SOP-5 原文處置內容完全不涉及路段層級改道，證實 M5 的「無條件 false」才是跟 SOP 語意一致的版本，M2-B 的條件式判斷是不必要的過度概化。已回頭更新 M5 design.md 的補註，從「待確認」改為「已確認」。
- **同時發現 SOP-2 的真實觸發條件是狀態/嚴重度/路段前綴的組合判斷，不是單純比對 `incident.type`**：M5 現在用型別查表能讓三筆固定事件跑出正確結果，但這是刻意的 Demo 範圍簡化，不是通用判定引擎，已在補註中如實記錄。

到此，規格文件與底層真實資料/原始 SOP 文字的一致性也完成交叉驗證，沒有發現新的落差。

---

## ✅ 已解決：`signaling_crowd_density.csv` 筆數誤植 37→36（五處統一修正）

直接讀取真實 CSV 逐行核對，發現實際資料列是 **36 筆**（`wc -l` 回報 37 是把標題列算進去的計算失誤），但 `02-data-contract.md`、`m1-data-ingestion/requirements.md`、`architecture-json-live.mmd`、`模組架構圖_整合版.md`、`資料流情境說明.md` 五處都寫「37 筆」，已統一修正。

除筆數外，用這份 CSV 逐一驗算了本次審查引用的全部人流黃金值——`BS_TPE_101`＝0.40（20:00 as-of）／0.45（22:15）、`BS_XY_ATT`＝0.30（21:45 as-of）、`BS_TPE_DOME`＝0.05（22:00）、`BL17 User_Count`＝31000／`growth`＝0.08（22:15 as-of）、`DOME` 歷史峰值＝40000／`growth`＝-0.31（22:00）——**全部與真實資料逐字吻合**，確認貫穿整個審查過程的核心數字沒有一個是憑空編造或算錯的。

至此，`data/` 五個 canonical 檔案（`city_traffic_flow.json`、`emergency_traffic_sop.json`、`live_incidents.json`、`road_network_topology.json`、`signaling_crowd_density.csv`）都已逐一讀取原始內容並跟全部規格文件交叉驗證完畢。

---

## ✅ 已解決：`architecture-json-live.svg` 是算圖後的舊產物，內容沒跟上 `.mmd` 的修正

之前修正 `architecture-json-live.mmd`（把 `126 筆·Is_Simulated=true→demo` 改成真實資料）時，只改了 mermaid 原始碼，沒有重新算圖，`.svg` 這個算圖產物裡還烙印著修正前的舊文字——判斷是「Kiro 不會讀圖片裡的文字」所以當時沒處理，但如果有人（隊友、評審）直接打開這張圖看，看到的是錯的數字。已用 `npx @mermaid-js/mermaid-cli` 重新從修正後的 `.mmd` 算圖，確認 `.svg` 現在顯示「36 筆・真實資料→provided」。

順便核對了「個人筆記與研究」裡另外兩張背景參考圖（`architecture-dataflow.svg`、`architecture-aws.svg`），把兩張圖的連線 ID 都拆解重建過拓樸（不只抓文字標籤），確認跟目前規格一致；`architecture-dataflow.svg` 有一條 `P3→C4` 直連(繞過A2)的舊草圖殘留，但已被後續設計取代、不影響現行規格，不用修。

---

## ✅ 已解決：WebSocket 推播事件 `message_type` 總表出現重複定義與遺漏

把全部規格裡定義的 `message_type` 收斂成一張表時才發現：`SPEC-O3` §5 定義的 `decision.result.v1`（完整 DecisionResult 推播）跟 `m5-api-orchestrator-dashboard/design.md` 既有的 `decision.completed.v1` 是**同一個事件、兩個名字**——分開核對兩份文件時沒連起來看，這次彙整總表才浮現。更嚴重的是：`SPEC-O3` 定義的 `decision.alert.v1`（F2 異常彈窗）、`decision.cycle_start.v1`、`decision.task_update.v1`（Agent 活動面板）三種推播事件，`M5` 的 `ws_manager.py` 廣播清單裡完全沒有對應的觸發點——這代表 F2 自動彈窗和 Agent 活動面板這兩個既定畫面功能，目前沒有人接線去推播資料給它們。

**已修正**：`SPEC-O3` 的 `decision.result.v1` 統一改名為 `decision.completed.v1`（`models.py` 唯一定義處，以 M5 既有命名為準）；`M5 design.md` 的廣播時機表從 4 處補齊為 7 處，新增三個事件的觸發時機與 payload 形狀，並註明由 `orchestrator.py` 呼叫 `ws_manager.broadcast()`（`ws_manager.py` 本身只管連線，不判斷何時推播）。

---

## ✅ 新增：`04-system-architecture.md`（給 Kiro 的正式大架構總覽）

彙整這次全部審查結果，寫成一份 always-load steering 文件，作為 Kiro 生成程式碼前的**第一份必讀**：一頁式系統定位、三層決策鐵律、模組地圖（含 `orchestrator.py` 雙owner說明）、端到端資料流程圖、完整 `message_type` 總表、`DecisionResult` 最終型別、七階段決策週期、三筆黃金事件驗收表、保底模式、加分項、文件地圖。

撰寫過程中把全部規格的 `message_type` 收斂成一張表時，順帶抓到並修正了上一節記錄的 WS 推播重複定義與遺漏問題——這也是寫總覽文件的價值之一：把分散在多份 spec 的定義攤開放在同一張表，容易看出個別核對時看不出來的落差。

---

## ⚠️ 已知缺口：`五人團隊分工與Spec開發建議書.md` 全篇缺失（非阻塞，僅記錄）

`00-tech-stack.md`、`01-module-boundaries.md`、`AWS服務選型建議.md` 等多份文件反覆引用這份文件作為「環境變數欄位」「Requirement ID（R1~R9）」「檢查清單」的權威來源，但團隊 Drive 下載內容裡**完全沒有這份檔案**（可能從未上傳，或遺漏在下載範圍外）。

**實際影響評估**：不阻塞 Kiro 生成程式碼。

- 環境變數清單（`AWS_REGION`／`BEDROCK_MODEL_ID`／`BEDROCK_KNOWLEDGE_BASE_ID`／`S3_DATA_BUCKET`／`DECISION_LOG_TABLE`／`USE_BEDROCK`）已在 `00-tech-stack.md` 第5節與 `AWS服務選型建議.md` 第六節重複列出，兩處一致，可直接採用。
- R1~R9 需求編號僅用於「這條規則對應原始需求哪一號」的追溯標記，各模組 spec 本身的 Acceptance Criteria 已寫得完整具體，缺少這份對照表不影響能否生成可運作的程式碼，只是少了追溯編號的註記。

若之後找到這份文件，或跟 Eric／何明哲確認過確實沒有這份文件，可移除本節。

---

## 🏗️ 建置順序（給 Kiro 的具體指令順序，不需要自己判斷）

所有規格文件都已備妥、衝突都已解決。依下列順序，一個階段完成、驗收測試通過後才進下一階段：

### 階段 0：共用基礎（全隊阻塞點，必須最先完成）
1. 餵 `m5-api-orchestrator-dashboard/requirements.md` 的 Requirement 1（共用型別）→ 生成 `src/models.py`、`contracts/module_exchange_contract.json`
2. 餵 `m5-api-orchestrator-dashboard/` 全部三份文件的「Mock 四端點 + `/ws` 骨架」任務段落 → 生成 `main.py`（含 `StubGateway`，讓其他模組能在還沒完成前先對接假資料）
3. 餵 `m5-api-orchestrator-dashboard/` 前端骨架任務段落 → 生成 `frontend/` 六分區骨架（先用假資料渲染）

### 階段 1：資料與感知（無外部依賴，可與階段2平行）
4. 餵 `m1-data-ingestion/requirements.md` 全文 → 生成 `src/loaders.py`、`src/rules.py`、`data_manifest.md`
5. 驗證：跑 `m1-data-ingestion/requirements.md` 第六節全部 10 項驗收測試，尤其第 1、2、5 項（真實漫遊率解析與 SOP-6 黃金值）

### 階段 2：路網推理（依賴 M1 的 `NormalizedDataBundle` 型別，但可先用假資料開發）
6. 餵 `m2-incident-routing/` 全部五份文件 → 生成 `src/routing.py`、`data/display_geometry.json`

### 階段 3：ETE 與報告生成（依賴 M1 + M2 的輸出型別）
7. 餵 `m4-decision-reporting/requirements.md` 全文 → 生成 `src/reporting.py`
8. 驗證：三筆黃金事件 ETE 值（90/70/41分）

### 階段 4：Agent、RAG 與 What-if
9. 餵 `m3-bedrock-advisor/K3-sop-rag/` 三份文件 → 生成 `src/bedrock_service.py` 的 RAG 檢索部分
10. 餵 `m3-bedrock-advisor/W1-whatif-agent/`、`W2-session-manager/` → 生成 `src/agent.py` 的 What-if 部分
11. 餵 `m3-bedrock-advisor/F6-chat-ui/` → 生成 `frontend/` 對話面板

### 階段 5：Orchestrator 核心邏輯（依賴前面全部模組的介面就緒）
12. 餵 `m4-explanation-chain-and-orchestrator/` 全部 6 份文件（`SPEC-00` 開頭讀）→ 生成 `src/orchestrator.py`（取代階段0的 `StubGateway` 呼叫，改接真實 M1/M2/M3/M4 模組）
13. 驗證：`SPEC-O2` 驗收測試表「黃金值回歸」（第11項，行號因文件後續修訂已變動，用內容比對不用行號）——ACC_001 全流程跑通，主004/次005/排除006、008/ETE 90分

### 階段 6：整合與 Demo 驗收
14. 前端從 Mock 切換為真實後端資料
15. 跑三筆真實事件（ACC_001/EVT_002/EVT_003）全流程，對照 `SPEC-00` 第5節黃金驗收值逐項確認
16. 確認 `USE_BEDROCK=false` 保底模式仍可跑完全流程（`00-tech-stack.md` 第6節硬性要求）

### 階段 7：加分項（P1，核心全部完成、驗收測試全過後才做）
17. 餵 `architecture-reference/加分項_AgentCore_Runtime部署.md` → 把 `src/agent.py` 的 Strands Agent 部署到 Bedrock AgentCore Runtime（CLI 步驟參考同資料夾 `AgentCore_Runtime_部署參考教學.md`）。這是團隊文件裡唯一提過的 AgentCore 加分項，範圍只到 Runtime 部署，不含 Memory/Gateway/Cognito 等其他 AgentCore 子服務；部署失敗不影響主流程，`main.py` 的 `POST /api/what-if` 呼叫鏈不依賴這一步。
