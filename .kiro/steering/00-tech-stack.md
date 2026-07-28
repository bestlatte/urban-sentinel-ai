---
inclusion: always
---

# 底層技術規則（Tech Stack Rules）

本檔是本專案**技術選型的唯一權威**。任何 spec、任務或程式碼不得引入本檔未列出的語言、框架或服務。若確有需要，先修改本檔再實作。

依據文件：`五人團隊分工與Spec開發建議書.md`（第六、十一章）、`模組架構圖_整合版.md`（第七章）、`AWS服務選型建議.md`。

---

## 1. 固定技術棧

| 層 | 固定選擇 | 說明 |
|---|---|---|
| 後端語言 | Python 3.12 | 全部後端邏輯，不混用其他語言 |
| Web 框架 | FastAPI + Uvicorn | **單一 Server**，同時提供 REST、`/ws` WebSocket 與 `frontend/` 靜態檔 |
| Schema 驗證 | Pydantic | 所有跨模組物件都必須是 Pydantic Model |
| 路網演算 | NetworkX | 有向圖；不得自行手寫圖演算法取代 |
| 資料處理 | pandas（可選） | 五檔皆 JSON，不需 openpyxl／CSV 解析 |
| 前端 | HTML5 + CSS3 + 原生 JavaScript | Grid/Flex/CSS Variables；深色指揮中心主題 |
| 前端通訊 | Fetch API + 原生 WebSocket | 不用 axios、socket.io |
| 圖表 | Chart.js（CDN，Demo 前落地 `frontend/vendor/`） | 時序圖與門檻線 |
| 地圖 | 原生 SVG 拓樸圖 | 資料**無 GIS 座標**，禁止使用 Leaflet/Mapbox 宣稱真實地圖 |
| LLM | Amazon Bedrock Foundation Model | 透過 boto3 / Strands Agents 呼叫 |
| Agent | Strands Agents SDK（跑在 FastAPI 內） | A2 Orchestrator 以 `@tool` 註冊 Python 工具 |
| RAG | Bedrock Knowledge Bases + S3（SOP 索引文件） | 向量庫用 S3 Vectors，建立失敗才改 OpenSearch Serverless |
| 儲存 | `data/` 五個 JSON + Python 記憶體 | 決策軌跡落地為記憶體／本機 JSON |
| Region | `us-west-2` | 全員一致，不得各用不同區 |

## 2. 明確禁止（不得寫入任何 spec 或程式）

- React / Vue / Next.js / Svelte、npm / Vite / webpack 等前端建置流程。
- PostgreSQL、TimescaleDB、Neptune、Redis、ElastiCache 等正式資料庫與快取（架構圖標註「正式版會用」即可，不實作）。
- Kafka / SQS / Redis Pub-Sub 等訊息中介；WebSocket 由 FastAPI 直接提供。
- Kubernetes / ECS / App Runner / 完整 CDK；前後端分開部署。
- 登入、Cognito、角色權限系統。
- 高併發、壓力測試、多環境（local/dev/prod）、完整 CI/CD。
- AgentCore Gateway / Memory / Identity / Browser / Code Interpreter。
  - AgentCore Runtime 僅為核心完成後的加分項，核心流程不得依賴它。
- DynamoDB 僅為決策軌跡的**選配**，核心流程不得依賴。

## 3. 固定目錄與檔案結構

新增檔案必須落在下列結構內；要新增未列出的模組檔，須先在 spec 說明理由。

```text
project/
├─ main.py                    # FastAPI 入口，掛載 frontend/ 與 API
├─ contracts/module_exchange_contract.json
├─ src/
│  ├─ models.py               # 全部 Pydantic Model（唯一定義處）
│  ├─ loaders.py              # 五 JSON 載入與 raw→normalized
│  ├─ rules.py                # SOP 規則與 A/B 級
│  ├─ routing.py              # 路網、上下游、主/次路線
│  ├─ agent/ 或 agent.py       # Strands Agent 與 @tool 註冊（What-if 邏輯較複雜時可拆成套件：agent/{whatif_agent,system_prompt,tools,response_formatter,loading}.py）
│  ├─ bedrock_service/ 或 bedrock_service.py  # Bedrock / KB 呼叫（RAG 檢索較複雜時可拆成套件：bedrock_service/{sop_retriever,bedrock_kb,local_fallback,sop_data}.py）
│  ├─ session/                # W2 對話狀態管理：session/{models,session_manager}.py（Turn／Session／W1Context，只存上下文不做判定）
│  ├─ reporting.py            # ETE、建議書、簡訊
│  ├─ ws_manager.py           # WebSocket 連線管理與廣播
│  └─ orchestrator.py         # 決策編排、組裝 DecisionResult；對外唯一入口見 `m4-explanation-chain-and-orchestrator/SPEC-O3`
├─ frontend/{index.html, css/, js/{app,api,ws,charts,map}.js, assets/, vendor/}
├─ prompts/{advisor.txt, report.txt, notification.txt}
├─ data/  # 五個 canonical JSON + display_geometry.json
├─ tests/  # 各模組單元測試，檔名對應 src/*.py（見各 spec「驗收測試」章節）
├─ scripts/  # 一次性開發/建置工具（如 K3 的 SOP 索引產生腳本、F6 的 mock WebSocket server），
│            # 不是應用程式讀取路徑的一部分，不隨 src/ 一起交付，Demo 前可忽略或刪除
├─ data_manifest.md
├─ pyproject.toml
└─ .env.example
```

## 4. API 表面（固定，不得擴充）

```text
GET  /api/dashboard           → DashboardPayload
POST /api/incidents/evaluate  → DecisionResult
POST /api/what-if             → WhatIfResult（前瞻假設問題）｜ TraceAnswer（回溯追問／無進行中週期，見
                                 m4-explanation-chain-and-orchestrator/SPEC-O3 §4 三分支路由規則）
GET  /api/health              → 簡單健康狀態
WS   /ws                      → 單向推播（server → client）
```

- 推播訊息一律使用 `模組間資料流通規格.md` 的 Message Envelope，前端以 `message_type` 分派。
- 所有改變狀態的操作走 REST；`POST` 必須同步回傳完整結果，WebSocket 只是額外通知。
- 前端斷線時自動重連並退回輪詢 `GET /api/dashboard`，Demo 不得因推播失效而中斷。
- 需要新端點時，先確認畫面真的無法用上述四個完成。

## 5. 環境變數

`.env.example` 的唯一來源是 `五人團隊分工與Spec開發建議書.md` 第七章：

```text
AWS_REGION / BEDROCK_MODEL_ID / BEDROCK_KNOWLEDGE_BASE_ID
S3_DATA_BUCKET / DECISION_LOG_TABLE / USE_BEDROCK
```

- 其他文件與 spec 不得另行定義欄位，只能引用。
- AWS 憑證由個人環境提供，**不得寫入程式碼、spec 或 Git**。

## 6. 保底模式（硬性要求）

`USE_BEDROCK=false` 時系統必須仍能跑完「感知 → 決策 → 通報」全流程：

- SOP 檢索改用本機關鍵字比對 `data/emergency_traffic_sop.json` 的 7 個 section，`retrieval_source = local_fallback` 並寫入 Envelope `warnings`。
- 建議書／簡訊改用 `reporting.py` 的固定模板。
- Agent 工具選擇改用「依事件類型查表」的固定流程。
- 規則、路網、ETE 三個決定性工具本來就是純 Python，不受影響。

任何實作不得讓核心流程在 Bedrock 不可用時完全失效。

## 7. 命名與格式

- JSON 欄位 `snake_case`；Pydantic Class `PascalCase`；Python 函式 `snake_case`。
- 道路 ID `RD_*`、站點 ID `BS_*`、SOP `SOP-1`～`SOP-7`。
- Message Type `<domain>.<action>.v<version>`。
- 時間一律 ISO 8601 + `Asia/Taipei`（`+08:00`），禁止無時區字串。
- 比率一律小數（`30%` → `0.30`）；百分比符號只在前端顯示層加。

## 8. 測試與 AI 協作規則

測試策略、docstring 規範、Kiro 產出程式碼時的協作原則，統一見 `03-testing-and-ai-collaboration.md`（同為 always-load steering，具同等拘束力）。
