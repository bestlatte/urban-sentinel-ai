---
inclusion: always
---

# 模組邊界規則（Module Boundary Rules）

本檔規定五個模組 spec 的**所有權界線**，防止各 spec 生成的程式互相覆蓋、重複實作或私接資料。

依據：`模組間資料流通規格.md` 第二／三章、`架構模組關係說明.md`、`模組架構圖_整合版.md` 第三章。

---

## 1. 五個模組 spec 與所有權

每個 spec 只能建立／修改「擁有檔案」欄位內的檔案。其他檔案**唯讀**。

| Spec（模組） | 契約模組代碼 | 架構節點 | 擁有檔案（可寫） |
|---|---|---|---|
| **M1 資料感知與規則** | `data_ingestion`、`sensing_rules` | D1–D4、P1–P5 | `src/loaders.py`、`src/rules.py`、`data_manifest.md` |
| **M2 事件與路網規劃** | `incident_routing` | R1–R5 | `src/routing.py`、`data/display_geometry.json` |
| **M3 Agent、RAG 與 What-if** | `bedrock_advisor` | A2 的 LLM 部分、K1/K3、W1/W2 | `src/agent.py`、`src/bedrock_service.py`、`src/session/`（W2）、`prompts/*` |
| **M4 ETE、建議書與通報** | `decision_reporting` | A3、C1–C4 | `src/reporting.py` |
| **M5 編排、API 與 Dashboard** | `api_orchestrator`、`dashboard` | API、A1、A2 編排（外殼）、A4（外殼）、FE | `main.py`、`src/models.py`、`src/ws_manager.py`、`frontend/**`、`src/orchestrator.py`（僅組裝/搬運程式碼，見下方 [2026-07-28更正]） |

> `src/models.py` 與 `contracts/module_exchange_contract.json` 屬 M5（架構整合）所有。其他模組**只能 import，不能新增或改欄位**；需要新欄位時，在 spec 中提出變更請求，由 M5 修改後其他模組才跟進。

> **[2026-07-28 總架構師補註] `src/orchestrator.py` 所有權已拆分，本表原寫「M5獨家」已過時**：團隊後續另外新增了 `m4-explanation-chain-and-orchestrator/`（`SPEC-00`／`SPEC-M4A`／`SPEC-M4B`／`SPEC-O1`／`SPEC-O2`／`SPEC-O3`，不在上表五個 spec 編號內，是額外的一份）。決議是：`orchestrator.py` 的**核心邏輯**（A1 分類、A2 編排分派、週期生命週期、A4 決策留痕、對外介面與路由）以 `m4-explanation-chain-and-orchestrator/` 為權威；M5 縮小範圍成「外殼」——`main.py`（端點掛載）、`src/ws_manager.py`、`src/models.py`（仍是全專案型別唯一定義處）、`frontend/**`。`src/orchestrator.py` 這一個檔案由兩份 spec 共同決定內容，實作時優先餵 `m4-explanation-chain-and-orchestrator/` 全部 6 份文件，`m5-api-orchestrator-dashboard/` 僅用於其中跟外殼相關的段落（詳見 `INDEX.md`「已決議」章節）。

## 2. 不可跨界的硬規則

1. **模組間只能透過契約物件交換資料**（`NormalizedDataBundle`、`SensingResult`、`RouteRequest`、`RoutePlan`、`BedrockAdvisory`、`EteEstimate`、`WhatIfRequest/Result`、`DecisionResult`、`DashboardPayload`）。禁止 import 其他模組的內部函式、私有變數或中間狀態。
2. **只有 M1 可以讀 `data/` 原始 JSON。** 其他模組一律使用 M1 產出的 `NormalizedDataBundle`。
3. **只有 M2 可以做路網演算。** 其他模組不得重算候選、上下游或排除理由。
4. **只有 M4 可以計算 ETE。** 公式與參數只有一份實作。
5. **只有 M1 可以判定 A/B 級與 SOP 命中。** M3 的 What-if 必須回頭呼叫 M1／M2／M4 的工具重算，不得自行判定。
6. **只有 M5 可以組裝 `DecisionResult` 與對外回應／推播。** 其他模組不得直接寫 response 或呼叫 WebSocket 廣播。
7. **前端不得重算任何規則。** `frontend/` 只顯示後端給的 `DecisionResult` / `DashboardPayload`；不得在 JavaScript 判定級別、篩路線或算 ETE。
8. **禁止重複實作。** 若某能力已屬其他模組，spec 必須呼叫它，而不是複製一份邏輯。
9. **不得繞過 A2 呼叫生成模組。** C1–C4（建議書／號誌／聯動／簡訊）一律由 A2 編排觸發。

## 3. 決策職責三層（不可混）

```text
選工具  = LLM        A2（Strands Agent）決定呼叫哪些工具
算答案  = Python     A/B 級、事件嚴重度、主/次路線、排除理由、ETE、恢復時間
寫文字  = LLM        建議書、簡訊、解釋敘述，只轉述上一層結果
```

LLM（含 A2、LLM_A2、W1、C1–C4）**絕對不得產生或修改**以下事實欄位：

```text
event_id / location / type / status / severity
traffic_level / rule_hits / clause_id
primary_route / secondary_route / exclusion_reasons
ete_minutes / estimated_recovery_at
SOP 條款編號與原文
```

- `BedrockAdvisory.fact_source` 固定 `python_decision_facts`。
- 任何 LLM 回答至少附一筆 `SopEvidence`。
- 數字、條款 ID、路線由 Python 注入 prompt，模型只負責敘述。

## 4. 固定資料流向（不得新增捷徑）

```text
data/*.json → M1(loaders) → NormalizedDataBundle
                              ├→ M1(rules) → SensingResult ─┐
                              └→ M5(orchestrator) ───────────┤
M5 → RouteRequest → M2(routing) → RoutePlan ─────────────────┤
M5 → M4(reporting) → EteEstimate / 報告 / Notification ──────┤
M5 → M3(agent+KB) → BedrockAdvisory ─────────────────────────┤
                                                             ▼
                                              M5 組裝 DecisionResult
                                              → A4 決策留痕（整份寫入）
                                              → REST 回應 + /ws 推播 → 前端
```

What-if：`前端 → M5 → M3 解析參數 → M1/M2/M4 重算 → M3 敘述 → WhatIfResult`。
**永遠 `simulation_only = true`，不得寫入決策軌跡，也不得改寫 `data/` 任何檔案。**

## 5. Spec 撰寫規則

每個模組 spec 必須包含且僅包含自己的範圍，並明列：

1. 對應的 Requirement ID（R1～R9，見 `五人團隊分工與Spec開發建議書.md` 9.1）。
2. 擁有的檔案清單（須與第 1 節一致）。
3. 輸入契約與輸出契約（用第 2 節列出的物件名，不自創格式）。
4. **禁止修改的共用欄位**與唯讀檔案清單。
5. 至少一組取自 `data/` 的真實範例輸入與期望輸出。
6. 保底行為（Bedrock／KB／推播失效時怎麼辦）。

Spec 不得包含：新框架、新資料庫、新 API 端點、其他模組的實作細節。

## 6. 衝突處理

遇到文件互相矛盾時，依此順序採信：

```text
1. contracts/module_exchange_contract.json   （機器契約，最高）
2. 模組間資料流通規格.md                     （[2026-07-28更正] 整份缺失，見下方說明，實際上跳過此項）
3. 中華電信_智慧交通命題說明.md              （驗收需求）
4. 五人團隊分工與Spec開發建議書.md            （同樣缺失，見 INDEX.md 已知缺口章節）
5. 模組架構圖_整合版.md / 架構模組關係說明.md
6. AWS服務選型建議.md
```

> **[2026-07-28 總架構師補註]** 搜尋整個專案（含 Drive 原始備份）都找不到 `模組間資料流通規格.md` 這份文件，可能從未上傳或遺漏在下載範圍外——跟 `INDEX.md` 已記錄的 `五人團隊分工與Spec開發建議書.md` 缺失是兩份不同的檔案，都缺。**實際影響評估**：不阻塞——這份文件原本負責的內容（Message Envelope 欄位、單位換算、SOP 門檻值等）已經被 `02-data-contract.md` 完整涵蓋，且第 1 節本來就寫「機器契約最高」，實務上核對這次全部規格時，凡遇到矛盾都是直接查 `02-data-contract.md`／`00-tech-stack.md`／或對照的其他 spec 解決，從未真的需要用到這份缺失的文件。若之後找到，或跟何明哲確認過確實沒有這份文件，可移除本節註記。

契約要改時的順序固定為：提出 Requirement ID → 說明受影響模組 → 改 `contracts/module_exchange_contract.json` → 改 `02-data-contract.md` 與 `models.py`（原寫「`模組間資料流通規格.md`」，該文件缺失，實際權威是 `02-data-contract.md`）→ 最後才改模組程式。
