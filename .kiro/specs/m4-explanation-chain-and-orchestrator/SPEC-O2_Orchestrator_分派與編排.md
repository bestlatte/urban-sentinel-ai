# SPEC-O2 Orchestrator：分派與編排（折衷制）— v1

> 依賴：SPEC-00、SPEC-O1。本文件定義週期 PLAN 與 EXECUTE 階段的完整行為，含**折衷制分派**與**複合事件編排（必做）**。

## 1. 折衷制總則

| 觸發來源 | 決定「叫誰做事」的機制 | 理由 |
|---|---|---|
| 規則觸發（§1-§6 自動流程） | **靜態分派表**（確定性，零 LLM） | 規則→動作由 SOP 明文寫死，無判斷空間；LLM 介入只有延遲、成本與漏連動風險 |
| 事件注入（live_incidents） | **A2 LLM 規劃器**（工具白名單 + 降級保底） | 事件為自然語言描述、類型開放，需要理解與規劃；此處為 agentic 價值所在 |

兩種機制產出的都是同一種 `DispatchPlan` 結構，EXECUTE 階段不區分來源。

## 2. 靜態分派表（規則觸發流程）

```
規則        → 任務（主責模組鏈）                         備註
§1-B / §1-A → [P5 摘要包 → C1]                        §1-A 附替代路徑引導建議
§2          → [R1→R2→R3→R4→R5, A3] → (X2) → C1..C4   R 鏈與 A3 可並行
§3          → [P5 摘要包 → C1, C3]                    C3 產北捷/公車聯動
§4          → [P5 摘要包（rules 追加 "§3"）→ C1, C3]   §4 自動連動 §3（見 2.1）
§5          → [COUNT_INTERSECTIONS(routing.py) → C1, C3]   警力 = 路口數 × 2；
                                                            [2026-07-28更正] 原寫「A1路口計算」，
                                                            A1 是事件分類器（SPEC-00 §2），語意不同，
                                                            改用 SPEC-00 §3.2 新增的 ToolName.COUNT_INTERSECTIONS，
                                                            函式歸屬 routing.py（模組2，需路網拓樸算受影響路口數）
§6          → 不分派；OPEN 後設 flag（SPEC-O1）
```

### 2.1 §4 連動 §3（確定性，不交 LLM）

批次含 §4 時，P5 任務的 `rules` 追加 `"§3"`，DISPATCH 紀錄 input 註明 `{"auto_chained":"§3","reason":"SOP §4 明文連動"}`。

### 2.2 同主責合併

同批次映射到同一模組鏈的多條規則合併為一個任務（`rules` 多元素），只發一次 DISPATCH。例：[§1-A, §4] → 一個 P5 任務 rules=["§1-A","§4","§3"]。

## 3. A2 LLM 規劃器（事件注入流程）

### 3.1 輸入輸出契約

```
輸入：A1 分類結果（事件 + 命中條款）+ P5 當前級別 + GlobalState 快照
輸出：ToolPlan { steps: [{tool: ToolName, args_hint: object}] }
```

規劃器以 Strands Agent（Bedrock）實作，system prompt 約束：

```
1. 只能從提供的工具白名單（SPEC-00 ToolName）中選擇。
2. 產出 JSON 格式的工具序列，不執行工具、不產生數值結果。
3. §2 類事件的序列必須包含 RAG_SEARCH 與 R 鏈工具與 CALC_ETE。
4. 不得省略 SOP 明文要求的步驟。
```

### 3.2 護欄（三層）

1. **白名單驗證**：ToolPlan 中出現非法工具名 → 整份計畫作廢，降級。
2. **必要步驟檢查**（確定性後驗）：依 A1 命中條款檢查計畫完整性（§2 必含 R 鏈 + CALC_ETE；§5 必含 COUNT_INTERSECTIONS）。缺漏 → 降級。
3. **逾時**：規劃器超過 8 秒未回 → 降級。

**降級目標**：改用靜態表中對應條款的預設鏈（§2 → 第 2 節的 §2 鏈）。降級時 record_step(A2, action="PLAN", input={"degraded": true, "reason": ...})。

### 3.3 記錄

規劃成功時 `record_step(A2, action="PLAN", input={事件摘要}, output={工具序列})`——LLM 的規劃決策本身入 Trace，是模組四「A2 這次選了哪些工具」的資料來源。

## 4. 複合事件編排（必做）

### 4.1 週期建構演算法

```
輸入：規則批次 TriggeredRule[] ∪ 注入事件（同 tick 合併）
1. OPEN + FLAGS（SPEC-O1；§6 移出批次）
2. 規則部分 → 靜態表建任務；事件部分 → LLM 規劃器建任務（失敗降級靜態鏈）
3. 同主責合併（2.2）
4. 組 DispatchPlan：
   Phase 1 (PARALLEL):   全部主責任務
                         // 主責彼此無依賴一律平行；單任務時退化為單發，無特例
   Phase 2 (SEQUENTIAL): X2 Red Team（FEATURE_RED_TEAM 且含 §2；context=R 鏈 output）
   Phase 3 (SEQUENTIAL): C1-C4 生成（context=前面全部 output + multilingual flag；
                         C4 僅 flag=true 時呼叫）
5. EXECUTE → SUMMARY → EXPLAIN → PUSH（SPEC-O1）
```

### 4.2 Phase 執行語意

- 每任務發出前：`record_step(A2, action="DISPATCH", input={rules/event, dispatch_to, mode})` → dispatch_seq 放入任務 context。
- **PARALLEL**：全部同時發出，join 等全部回報或逾時；任一失敗不中斷其他。
- **SEQUENTIAL**：前一任務 output 併入後一任務 context。
- 執行模組寫 record_step 時以 dispatch_seq 為 parent_seq（DAG 歸屬）。

### 4.3 逾時預算

```
CYCLE_BUDGET_MS = 60000（命題 60 秒）
單任務 deadline = min(該模組預設逾時, 週期剩餘預算)
預設：P5 摘要 15s / R 鏈 20s / X2 15s / C 系列 20s / LLM 規劃器 8s
```

## 5. 降級規則（永不沉默）

| 失敗點 | 降級行為 |
|---|---|
| LLM 規劃器 | 改用靜態鏈（3.2） |
| P5 或 R 鏈任務逾時/錯誤 | 該分支缺席；C1 對應段落顯示「本節分析未能於時限內完成 + trace_id」；補記 AGENT_TIMEOUT |
| X2 Red Team | 直接跳過（延伸功能，缺席即基本行為） |
| C 系列生成失敗 | 將各模組結構化 output 原樣打包推送，標示「報告生成失敗，以下為原始結果」 |
| EXPLAIN（M4B）失敗 | 報告該段顯示佔位文字 + trace_id（M4B 契約） |

## 6. 驗收測試（決定性，模組以 mock 代替）

| # | 情境 | 預期 |
|---|---|---|
| 1 | 規則批次 [§2] 不經 LLM | LLM 規劃器 mock 呼叫次數 = 0；DISPATCH 依靜態表 |
| 2 | 事件注入經 LLM 規劃 | PLAN 紀錄存在且 output 含工具序列 |
| 3 | 規劃器回非法工具名 | 計畫作廢；PLAN 紀錄 degraded=true；改走靜態 §2 鏈 |
| 4 | 規劃器漏 CALC_ETE（§2 事件） | 必要步驟檢查攔截 → 降級靜態鏈 |
| 5 | 複合 [§1-A + 事件注入] | Phase 1 兩筆 DISPATCH；兩 mock 執行時間區間重疊（真平行）；join 後才進 C1 |
| 6 | [§1-A, §4] 合併 + 連動 | 僅一筆 P5 DISPATCH，rules=["§1-A","§4","§3"]，含 auto_chained 註記 |
| 7 | P5 分支逾時 | AGENT_TIMEOUT 紀錄存在；R 鏈正常；C1 仍被呼叫且 perception 欄位 null |
| 8 | C1 失敗 | 推送內容為原始 output + 失敗標示；不拋出不沉默 |
| 9 | FEATURE_RED_TEAM=false | 無 X2 DISPATCH；流程直達 C 系列 |
| 10 | §6 + §2 複合 | C4 被呼叫（multilingual=true）；§6 無 DISPATCH |
| 11 | 黃金值回歸 | ACC_001 全流程 mock 整合：主 004 / 次 005 / 排除 006、008 / ETE 90 分（SPEC-00 §5） |
