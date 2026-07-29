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
