# SPEC-00 共同基礎規格（憲法）— v1

> 全隊共用的命名、列舉、慣例與鐵律。所有其他 SPEC（O1-O3、M4A、M4B）與程式碼皆遵循本文件；本文件凍結後如需變更，須全隊同步。

## 1. 兩大鐵律

1. **LLM 只表達、不改寫**：所有 LLM 節點（A2 規劃、C1-C4 生成、W1 What-if、M4B 解釋）只能表達確定性工具算出的結果，不得改寫事件 ID、位置、級別、路線、ETE 數值或 SOP 條款編號。數字與判定的唯一來源是 P/R/A3 系列工具。
2. **前端不重算**：前端只顯示後端給的 `DecisionResult`，不在 JavaScript 重算規則、路線或 ETE。

## 2. 命名對照表（模組代號 ↔ 概念名）

程式碼與 Trace 以**模組代號**為準；概念名（Agent 名）僅用於簡報與口頭溝通。

| 代號 | 概念名 | 性質 | 職責 |
|---|---|---|---|
| D1-D4 | 資料層 | 確定性 | 載入、校驗、時間標準化、事件注入監聽 |
| P1-P5 | Perception（感知） | **確定性規則引擎** | 三指標計算（P1 飽和度 / P2 成長率 / P3 漫遊率）、SOP 門檻比對（P4）、級別判定（P5） |
| R1-R5 | Incident Response（路網） | 確定性工具鏈 | 建圖、上下游判定、候選篩選、主次路徑、排除理由記錄 |
| A1 | 事件分類器 | 確定性 | 事件 → SOP 條款映射 |
| A2 | Orchestrator | **LLM（Strands + Bedrock）+ 確定性分派表** | 編排中樞；分派策略見 SPEC-O2 折衷制 |
| A3 | ETE 計算 | 確定性 | SOP §7 公式 |
| A4 | Decision Trace Logger | 確定性 | 模組四記錄層（SPEC-M4A） |
| C1-C4 | Communication | LLM | C1 建議書 / C2 號誌配時 / C3 跨系統聯動 / C4 多語簡訊 |
| W1-W2 | Strategy Advisor | LLM + 重算 | What-if 問答（W1）、對話狀態（W2） |
| K3 | RAG 檢索 | 檢索 | SOP 向量庫查詢（Bedrock KB） |
| X1 | Simulation（延伸） | 確定性模型 | 時序預測推演；feature flag 控制 |
| X2 | Red Team（延伸） | 確定性驗證 + LLM 表達 | 方案壓力測試；feature flag 控制 |

## 3. 共用列舉

### 3.1 ActorCode（Trace 的 agent 欄位合法值）

```
A1, A2, A3, A4, P5, R1, R2, R3, R4, R5, C1, C2, C3, C4, W1, X1, X2
```

### 3.2 ToolName

```
RAG_SEARCH             // K3 SOP 檢索
GRAPH_BUILD            // R1
UPSTREAM_JUDGE         // R2
CANDIDATE_FILTER       // R3
ROUTE_SELECT           // R4
CALC_ETE               // A3
COUNT_INTERSECTIONS    // [2026-07-28新增] SOP-5 警力估算用；歸屬 routing.py（模組2），需路網拓樸算受影響路口數，不沿用 A1（A1 是事件分類器，語意不同，SPEC-O2 §2 原寫「A1路口計算」是誤用）
CAPACITY_CHECK         // X2 用（延伸）
FORECAST_MODEL         // X1/X2 用（延伸）
CASCADE_ANALYSIS       // X2 用（延伸）
FORMAT_REPORT          // C1
TRANSLATE              // C4
```

### 3.3 ReasonCode（候選路徑排除理由；對齊 R5 的九項條件）

> [2026-07-28 總架構師補註] 原列舉只有七值，跟 `m2-incident-routing/模組2C_本機路網重規劃引擎_第一階段Spec.md` 的 R5 實際產出的 9 種原因碼對不起來——M2-C 會產生 `missing_traffic_snapshot`（找不到飽和度快照時預設排除）與 `unknown_segment`（alternatives 指向不存在的路段代碼）兩種情況，原本不在列舉裡。`SPEC-M4A` 的 `record_step()` 對 `reason_code` 是 fail-fast 驗證，遇到列舉外的值會直接拋 `ValueError` 中斷寫入——這不是邊角案例，是 R1-R5 正常運作路徑上就會發生的情況。已補齊列舉為九值；M2-C 原本用的 lower_snake_case 命名（`closed_or_affected` 等）已改用跟本列舉一致的 UPPER_SNAKE_CASE（SPEC-00 是列舉唯一來源，各模組寫入時一律換算成這套命名，不得各自保留原始大小寫）。

```
CLOSED                     // 事故封閉
CAPACITY_INSUFFICIENT      // 容量 < 1000
NOT_IN_ALTERNATIVES        // 非候選（alternatives 未提供該方向）
NOT_DIRECTLY_INTERSECTING  // 非直接相交
DOWNSTREAM_ONLY            // 僅位於下游
FLOW_DIRECTION_MISMATCH    // 流向不符
SATURATED                  // 飽和度 ≥ 0.85 且尚有其他合格候選
UNKNOWN_SEGMENT            // alternatives 指向的路段代碼不存在於路網
MISSING_TRAFFIC_SNAPSHOT   // 找不到 as-of 車流快照，資料缺口非零值
```

### 3.4 FindingCode（非排除類的結構化發現）

```
SATURATED_BUT_RETAINED  // 唯一合格候選雖飽和仍保留為主線 + 長綠燈 +25%（SOP-2 例外）
CAPACITY_OVERLOAD       // 容量超載（X2 算術驗證；延伸）
PREDICTED_COLLAPSE      // 預測將達癱瘓（X1/X2；延伸）
CASCADE_RISK            // 連鎖崩潰風險（X2；延伸）
SCENARIO_COMPARED       // 多方案比較結果（X1；延伸）
```

## 4. 全域慣例

- **trace_id 格式**：`TR-YYYYMMDD-HHMM-<3位流水號>`，由 A2 於決策週期開始時生成。
- **時間格式**：一律 `YYYY-MM-DD HH:MM`（SOP §6 規定）；Trace 內部 timestamp 用 ISO 8601 含秒。
- **單位正規化（D1-D3 責任，P 系列不得再轉換）**：`Roaming_User_Pct`（[2026-07-28更正] 真實資料為「帶 % 符號字串」如 `"40%"`，須先移除 `%` 再除以 100 → `0.40`；原文寫的 `32.0` 裸數字格式是已淘汰的模擬資料格式）；`Growth_Rate` 已是小數率，不可再轉換。P3 拿到的一律是 `0.0-1.0`。SOP 門檻對應：漫遊 `≥ 0.30`、成長率 `> 0.30`。
- **模擬資料標示**：[2026-07-28更正] `signaling_crowd_density.csv` 已是主辦方提供的真實資料，`provenance="provided"`，不再是 `Is_Simulated=true` 的模擬資料，前端不需標示 Simulated/Demo（其餘來源如仍有 demo 補值才需標示）。
- **級別門檻**：`Saturation ≥ 0.95` → A 級；`0.85 ≤ Sat < 0.95` → B 級。
- **雙通道保底**：REST POST 同步回傳與 WebSocket 推播為同一份 `DecisionResult`；推播失效時 POST 回傳為保底。
- **What-if 不寫稽核**：W1 的模擬問答不呼叫 `open_trace` / `record_step`（不污染 DB5）。

## 5. 黃金驗收值（全隊測試共用斷言）

### 5.1 三事件 ETE 固定值

| 事件 | severity | ETE | 備註 |
|---|---|---|---|
| TPE_2026_ACC_001（光復南路塌陷） | Critical | **90 分** | 60 + (1.0-0.5)×60；恢復 2026-05-20 23:40 |
| EVT_002 | — | **70 分** | 依資料集實算 |
| EVT_003 | — | **41 分** | 依資料集實算 |

### 5.2 ACC_001 路徑篩選固定結果（RD_TPE_002，alternatives=[004,005,006,008]）

| 候選 | 判定 | 依據 |
|---|---|---|
| RD_TPE_004 | **主要路線** | 容量 2500、Sat 0.78、上游直接相交 |
| RD_TPE_005 | **次要路線** | 容量 4000、Sat 0.65、下游直接相交 |
| RD_TPE_006 | 排除 | NOT_DIRECTLY_INTERSECTING |
| RD_TPE_008 | 排除 | CAPACITY_INSUFFICIENT（600 < 1000） |

### 5.3 飽和例外規則（R3/R4 行為契約）

```
候選 Sat ≥ 0.85：
  尚有其他未飽和合格候選 → 排除，記 ReasonCode.SATURATED
  為唯一合格候選         → 保留為主線，記 FindingCode.SATURATED_BUT_RETAINED
                           + 長綠燈時制、綠燈延長 25%
```

### 5.4 多語觸發基準（22:00 as-of）

> [2026-07-28 更正] 原基準值（`BS_TPE_DOME = 0.32`、`BS_TPE_101 = 0.30`）依據的是 GPT 生成的模擬人流資料。黑客松主辦方已補齊真實 `signaling_crowd_density.csv`，實測 `BS_TPE_DOME` 漫遊率全程僅 5~6%，不會觸發。已依真實資料重新驗算如下。

`BS_TPE_101 = 0.40`（20:00 as-of，22:15 further升至0.45）、`BS_XY_ATT = 0.30`（21:45 as-of）→ SOP §6 成立 → C4 觸發。`BS_TPE_DOME` 不再作為觸發依據。

其餘黃金驗收值（ETE 90/70/41分、SOP-3捷運分流以BL17 User_Count>25000觸發、SOP-4大巨蛋散場以峰值40000+growth-0.31觸發）不受人流資料格式變更影響，數值不變。

## 6. 文件地圖

| 文件 | 內容 | 主要讀者 |
|---|---|---|
| SPEC-00（本文件） | 命名、列舉、慣例、黃金值、鐵律 | 全隊 |
| SPEC-O1 | 週期生命週期、GlobalState、排隊、模組四呼叫時序 | Orchestrator 開發者 |
| SPEC-O2 | 折衷制分派（靜態表 + LLM 規劃器）、複合事件編排、降級 | Orchestrator 開發者 |
| SPEC-O3 | 對外介面、輸入路由、DecisionResult、雙通道 | Orchestrator + 前端 |
| SPEC-M4A | Trace 記錄層（純確定性） | 模組四開發者 |
| SPEC-M4B | 解釋生成層（LLM） | 模組四開發者 |
