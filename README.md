# 城市應變分析 AI Agent（CityNexus）

> 2026 雲湧智生：台灣生成式 AI 應用黑客松 —— 中華電信企業命題

一套半自動的**交通事件應變決策支援系統**：感測資料 → 規則判定等級 → 路網重規劃 → LLM 生成建議書/簡訊 → 指揮官在單一 Dashboard 上看到並可對系統提問（What-if 模擬 / 回溯追問已做的決策）。**系統不自動執行任何交通管制動作**，只產出建議與說明；動手做決定的是人。

## 核心設計原則：三層決定職責

```text
選工具  = LLM        Agent（Strands）決定呼叫哪些工具，不產生事實
算答案  = Python     A/B級、事件嚴重度、主/次路線、排除理由、ETE、恢復時間——全部決定性計算
寫文字  = LLM        建議書、簡訊、解釋敘述，只轉述上一層已經算好的事實，不得改寫任何數字/ID/條款編號
```

這條界線是整個系統最在意的正確性保證：LLM 可以「選要不要呼叫工具」「把算好的事實寫成人話」，但永遠不能捏造或修改事件 ID、位置、級別、路線、ETE 或 SOP 條款編號。

## 快速開始

```bash
# 安裝依賴
pip install -e ".[dev]"

# 跑測試（111 條，golden value 精確斷言）
pytest tests/ -v

# 啟動伺服器（本機保底模式：Stub 資料 + 不呼叫 Bedrock，不需要 AWS 憑證）
USE_STUB_MODULES=true USE_BEDROCK=false uvicorn main:app --reload

# 啟動伺服器（真實模組 + 保底模板，不需要 AWS 憑證）
USE_STUB_MODULES=false USE_BEDROCK=false uvicorn main:app --reload

# 啟動伺服器（真實模組 + 真 Bedrock 呼叫，需要 AWS 憑證與 Bedrock model access）
USE_BEDROCK=true uvicorn main:app --reload
```

伺服器啟動後開瀏覽器連到 `http://127.0.0.1:8000/frontend/index.html`。

環境變數完整說明見 [`.env.example`](.env.example)。

## LINE 通報設定

報告卡片上的「發送至 LINE」會把 C4 產出的多語通報送到 LINE 官方帳號。

**先講兩件會省你時間的事：**

- **LINE Notify 已於 2025-03-31 終止服務**，網路上多數「一行 curl 發 LINE」的教學都失效了。現在唯一的路是 Messaging API。
- push / broadcast 都是**我們主動打出去**的 HTTPS 請求，**不需要 webhook、不需要公開網址、不需要 ngrok**。webhook 只有在要「接收」訊息時才需要。

### 取得憑證（約五分鐘）

#### 情況 A：已經有官方帳號（在 LINE Official Account Manager 建的）

如果你手上只有一個**基本 ID**（`@` 開頭，例如 `@416vdvci`），代表帳號是在
OA Manager 建的、**還沒開啟 Messaging API**。沒開啟的話 LINE Developers Console
裡不會有對應的 channel，當然也找不到 token。先補這一步：

1. 到 [LINE Official Account Manager](https://manager.line.biz/) 選該帳號
2. 右上角 **設定** → 左側選單最下面 **Messaging API**
3. 點 **啟用 Messaging API** → 選（或現場建立）一個 **Provider**
4. 完成後該頁會出現 Channel ID 與 Channel secret，接著跳到下面第 4 步去拿 token

#### 情況 B：從零開始

1. 用你的 LINE 帳號登入 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立一個 **Provider**（名稱隨意，例如 `urban-sentinel`）
3. 在該 Provider 底下建立 Channel，類型選 **Messaging API**
   （**不要選 LINE Login**——它的 token 推不了訊息，會回 403）

#### 兩種情況都要做的

4. 進入 channel 的 **Messaging API** 分頁：
   - 最下方 **Channel access token (long-lived)** → 按 **Issue**，複製 token
   - 同一頁上方有 **QR code** → **用手機 LINE 掃描，把這個官方帳號加為好友**
     （這步最常被漏掉；沒加好友就收不到任何訊息，而且 API 會回 400）
5. 若要指定收件人：**Basic settings** 分頁最下方的 **Your user ID**（`U` 開頭）
   就是你自己的 userId。不想處理這步就留空，系統會改用 broadcast。

> **四個很像的東西，只有一個是我們要的**（這裡卡住的人最多）：
>
> | 你看到的 | 在哪一頁 | 是不是憑證 |
> |---|---|---|
> | 基本 ID `@416vdvci` | OA Manager | ✗ 公開帳號名稱，給人搜尋加好友用 |
> | Channel ID（一串數字） | Basic settings | ✗ |
> | Channel **secret** | Basic settings | ✗ 最常被誤認成 token |
> | **Channel access token (long-lived)** | **Messaging API 分頁最下方** | ✓ **就是這個**，通常 170+ 字元 |
6. 填進 `.env`：

```bash
LINE_CHANNEL_ACCESS_TOKEN=你剛剛複製的 token
LINE_TO_USER_ID=            # 留空 = broadcast 給所有好友（個人 Demo 建議留空）
LINE_ENABLED=true
```

重啟伺服器讓 `.env` 生效。

### 驗證

```bash
# 設定狀態（不會回傳 token 本身）
curl http://127.0.0.1:8000/api/notify/line/status

# 直接送一則測試訊息到你的 LINE
python -m scripts.send_line_test "測試訊息：城市應變系統連線正常"
```

手機收到訊息就代表通了。之後在 Reports 頁面選一起事件、按「發送至 LINE」即可。

### 行為與限制

- 送出的是**通報簡訊**（C4 產出，短），不是交控建議書全文——後者好幾百字，手機上是一整片牆
- **只有按下按鈕才會送**。決策週期與路線重規劃**不會**自動發送：對外發送不可逆，而免費方案每月訊息則數有上限
- 同樣內容 60 秒內不重送（避免連點與 WebSocket 重連把額度燒在重複訊息上）
- 送不出去時，錯誤訊息會直接告訴你該做什麼（token 失效、沒加好友、用錯 channel 類型各自對應不同處置）

## 三筆黃金驗收事件

| 事件 | 類型 | 主因 SOP | 主/次路線 | ETE |
|---|---|---|---|---:|
| `TPE_2026_ACC_001` | 路面塌陷 | SOP-2（並1、3、4、6、7） | `RD_TPE_004` / `RD_TPE_005` | **90 分鐘** |
| `TPE_2026_EVT_002` | 人群推擠 | SOP-3（並4、6、7） | — | **70 分鐘** |
| `TPE_2026_EVT_003` | 號誌故障 | SOP-5（並1、3、4、6、7） | — | **41 分鐘** |

在 Dashboard 的「Event Injection」面板點選任一事件即可觸發完整七階段決策週期（OPEN→FLAGS→PLAN→EXECUTE→SUMMARY→EXPLAIN→PUSH），F7 活動面板會即時顯示路網規劃/ETE計算/報告生成的進度。

## 系統架構

```
main.py (FastAPI) → orchestrator.py (A1分類/A2編排/A4留痕)
                        │
      ┌─────────────────┼─────────────────┐
      ▼                 ▼                 ▼
  rules.py          routing.py       reporting.py
  (P1-P5規則引擎)    (R1-R5路網規劃)   (A3 ETE + C1-C4 建議書/簡訊)
      │                 │                 │
      └─────────────────┴─────────────────┘
                        ▼
              bedrock_service/ (K3 SOP RAG)
              agent/ (W1 What-if Agent, A2 Agent)
                        │
                        ▼
              decision_trace.py (決策留痕，供 F7 解釋面板追問)
```

跨模組存取一律經由 `orchestrator.py` 的 `GATEWAY`（`ModuleGateway` Protocol，`Stub`/`Live` 兩種實作可切換），不直接 import 其他模組的函式。

### 目錄結構

| 路徑 | 內容 |
|---|---|
| `src/loaders.py` | D1-D4：五個 canonical 資料檔載入與正規化 |
| `src/rules.py` | P1-P5：感知運算 + SOP 規則引擎（零 LLM） |
| `src/routing.py` | R1-R5：路網重規劃（零 LLM，60 秒 SLA） |
| `src/reporting.py` | A3 ETE 計算 + C1-C4 建議書/簡訊生成 |
| `src/orchestrator.py` | A1 事件分類、A2 編排、A4 決策留痕、對外路由 |
| `src/decision_trace.py` | 決策軌跡記錄與生成層（供 F7 解釋鏈） |
| `src/whatif_engine.py` | What-if 覆寫重算引擎 |
| `src/bedrock_service/` | K3 SOP RAG 檢索（本機關鍵字保底 / Bedrock KB） |
| `src/agent/` | W1 What-if Agent、A2 Agent 工具、loading 推播 |
| `src/session/` | W2 對話狀態管理 |
| `src/models.py` | 全專案型別唯一定義處（Pydantic） |
| `frontend/` | Dashboard（原生 HTML/CSS/JS + Chart.js + SVG，無建置流程） |
| `data/` | 五個 canonical 資料檔（車流、人流、路網、事件、SOP） |
| `scripts/` | 一次性建置工具（SOP 索引產生、S3 上傳） |
| `tests/` | 111 條測試，golden value 精確斷言 |

## 文件地圖

需要實作細節時依此順序查：

1. `.kiro/steering/00-tech-stack.md` — 固定技術棧、目錄結構、禁用清單
2. `.kiro/steering/01-module-boundaries.md` — 模組所有權
3. `.kiro/steering/02-data-contract.md` — 資料/公式/黃金值
4. `.kiro/steering/03-testing-and-ai-collaboration.md` — 測試要求
5. `.kiro/steering/04-system-architecture.md` — 系統架構總覽（第一份必讀文件）
6. `.kiro/specs/<模組>/` — 個別模組實作細節
7. `INDEX.md` — 全部已知問題與修正歷史
8. `KIRO_BUILD_CHECKLIST.md` — 開發順序與目前進度（Phase 0-13 已完成，Phase 14 為需要 AWS 環境的加分項）
9. `.kiro/specs/architecture-reference/2026-07-28_架構圖合規性複查與待辦.md` — 架構圖合規性複查發現與修正紀錄

## 目前狀態

- **Phase 0-13**：全部完成，111 passed，三筆黃金事件精確驗證通過。
- **Phase 14**（Bedrock KB 建立、真 Bedrock 呼叫驗證、Guardrails、AgentCore Runtime 部署）：需要真實 AWS 環境，排定於比賽當天進行，詳見 `KIRO_BUILD_CHECKLIST.md`。
- 保底模式（`USE_BEDROCK=false`）下全流程不中斷：SOP 檢索退化為本機關鍵字比對、建議書退化為固定模板，三個決定性工具（規則/路網/ETE）本來就是純 Python 不受影響。
