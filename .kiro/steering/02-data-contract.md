---
inclusion: always
---

# 資料契約與驗收規則（Data Contract Rules）

本檔規定所有模組共用的資料來源、單位、關聯與驗收數值。實作與 `模組間資料流通規格.md` 不一致時，以機器契約 `contracts/module_exchange_contract.json` 為準。

---

## 1. 唯一資料來源（canonical）

| logical_type | 檔案 | 筆數／結構 | classification |
|---|---|---|---|
| `traffic` | `data/city_traffic_flow.json` | 112 | `provided` |
| `crowd` | `data/signaling_crowd_density.csv` | 36（[2026-07-28更正] 原寫37筆，是 `wc -l` 把標題列算進去的計算失誤，實際資料列36筆；時間點不規則，9 站） | `provided`（2026-07-28 主辦方補齊真實資料，取代原模擬版） |
| `road_network` | `data/road_network_topology.json` | 15 | `provided` |
| `incident` | `data/live_incidents.json` | 3 | `provided` |
| `sop` | `data/emergency_traffic_sop.json` | 7 sections | `provided` |

- 不得新增、改名或複製其他資料檔（`data/display_geometry.json` 為唯一例外，僅供 SVG 顯示，不參與演算法）。
- 不得直接用 raw JSON 去驗證機器契約；raw 與 normalized 是兩層格式，必須先經 loader 映射。
- SOP 的 source of truth 永遠是 JSON；上傳 S3 的索引文件只是衍生物，兩者不得各自修改。
- 人流資料已由主辦方於 2026-07-28 補齊真實 `signaling_crowd_density.csv`，classification 為 `provided`，**不再標示 Simulated / Demo**。原模擬版本（`Is_Simulated=true`、126筆、9站每15分鐘一筆）已棄用，僅保留備份供比對。

## 2. 強制正規化（只在 loader 做一次）

```text
Timestamp        → ISO 8601 + 08:00（Asia/Taipei）
Pascal/混合欄位  → snake_case（含真實CSV的 BS_ID→station_id、Location_Name→station_name）
Growth_Rate      → 已是小數率，禁止再除以 100
Roaming_User_Pct → 真實資料為「帶%符號字串」（如 "40%"），須先移除 % 再除以 100 → 0.40；
                    不得假設為純數字型態（此為 2026-07-28 更正，與舊模擬版格式不同）
section_number=N → clause_id = "SOP-N"
Incident 缺 affected_road → null
```

下游（P 系列、routing、reporting、前端）只會看到 `0.0~1.0` 的比率。任何模組不得二次換算。

## 3. 關聯與 Join 規則

```text
TrafficSample.segment_id      → RoadSegment.segment_id
Incident.affected_segment RD_*→ RoadSegment.segment_id
Incident.affected_segment BS_*→ RoadSegment.nearby_stations[]
Incident.affected_road        → RoadSegment.segment_id（優先於周邊推導）
RoadSegment.alternatives[]    → segment_id（單向，禁止自動建反向邊）
RoadSegment.intersections[]   → RoadSegment.name（需建 name_to_segment_id）
CrowdSample.station_id        → RoadSegment.nearby_stations[]
```

- 時間 Join 固定 as-of：取 `timestamp <= incident.timestamp` 的最近一筆，**不做插值**（`selection_method = latest_at_or_before_incident`）。
- `intersections` 依「上游 → 下游」排序，供 SOP-2 上游分流判定。
- `正氣橋` 等不在資料集的名稱視為外部交會點，只產生 warning，不得使整批載入失敗。
- `nearby_stations: []` 是合法值，不是缺資料，不得自行補值。
- 主鍵一律用 ID（`RD_*` / `BS_*` / `event_id`），中文名稱只用於顯示。

## 4. 分級與門檻（決定性）

```text
交通等級（traffic_level）：saturation_score >= 0.95 → A
                           0.85 <= score < 0.95    → B
                           其他                     → normal
事件嚴重度（event.severity）：Critical | High | Medium   ← 兩者不可混用
SOP-3：Growth_Rate > 0.30 或 User_Count > 25000
SOP-4：歷史峰值 >= 30000 且 Growth_Rate <= -0.20
SOP-6：任一站點 roaming_user_pct >= 0.30 → 多語通報（由 A2 觸發 C4）
```

`severity: "A"` 是錯誤用法，禁止出現。

## 5. 路網篩選規則

硬性排除（[2026-07-28更正] 統一改用 `m4-explanation-chain-and-orchestrator/SPEC-00` §3.3 `ReasonCode` 的正式命名，避免第三套寫法）：`CLOSED`（原寫 `incident_blocked`）、`CAPACITY_INSUFFICIENT`（原寫 `capacity_below_1000`）、`NOT_IN_ALTERNATIVES`（原寫 `not_in_alternatives`）、`NOT_DIRECTLY_INTERSECTING`（原寫 `not_direct_intersection`）、`DOWNSTREAM_ONLY`（原寫 `downstream_only`）、`FLOW_DIRECTION_MISMATCH`（原寫 `flow_direction_mismatch`）；另有 `UNKNOWN_SEGMENT`、`MISSING_TRAFFIC_SNAPSHOT` 兩值（見 `SPEC-00`），本節未列出。

飽和（`saturation_score >= 0.85`）採兩段式：

```text
├─ 還有其他未飽和的合格候選 → 排除，記 saturated（預設行為）
└─ 它是唯一合格候選         → 保留為主線：eligible=true、
                               記 saturated_but_retained、
                               expected_actions 加「啟動長綠燈時制、綠燈延長 25%」、
                               RuleHit 引用 SOP-2
```

- 不得因飽和而回傳空的 `primary_route`；真的無候選才回 `NO_FEASIBLE_ROUTE`。
- 每個候選都必須留下可解釋理由，供決策依據面板顯示。
- 路網重規劃必須量測 `duration_ms` 並設定 `within_60_second_sla`（`<= 60000`）。

## 6. ETE 固定公式

```text
ETE = base_clearance + max(0, (average_saturation - 0.5) * 60)
base_clearance: Critical=60、High=40、Medium=20
```

取值順序：有 `affected_road` 用它，否則用 RD 類 `affected_segment`；多條才取平均。

**固定驗收值（實作結果必須完全一致）：**

| 事件 | 主因 SOP | ETE | 備註 |
|---|---|---:|---|
| `TPE_2026_ACC_001` 路面塌陷 22:10 | SOP-2（並命中 1、6、7） | 90 分 → 23:40 | 主 `RD_TPE_004`、次 `RD_TPE_005`；`RD_TPE_006` 非直接相交排除、`RD_TPE_008` 容量 600 排除 |
| `TPE_2026_EVT_002` 人群推擠 22:20 | SOP-3（並命中 4、6、7） | 70 分 | [2026-07-28 更正] 22:15 as-of BL17 User_Count=31,000（真實資料，觸發依據為 User_Count>25000，非growth_rate；真實growth=0.08）；`affected_road=RD_TPE_001` |
| `TPE_2026_EVT_003` 號誌故障 22:30 | SOP-5（並 7） | 41 分 | `RD_TPE_007` saturation=0.85 → B 級；不得誤判為 SOP-1 城市級或 SOP-2 |

算出的數字與上表不符時，先檢查 as-of join、百分點轉換與 SOP-2 路由條件，不要改公式。

## 7. Envelope 與可追溯性

- 所有跨模組訊息與 API 回應（除 `/api/health`）使用同一份 Message Envelope，含 `schema_version`、`message_id`、`correlation_id`、`message_type`、`source_module`、`target_module`、`generated_at`、`status`、`provenance`、`warnings`、`errors`、`payload`。
- 同一次事件或 What-if 流程共用同一個 `correlation_id`。
- 主要輸出必須帶 `provenance`，並正確標記 `provided` / `demo` / `derived` / `generated`。
- 錯誤碼只能用契約定義的八種（[2026-07-28更正] 原寫「九種」但只列出 8 個，核對本次全部 spec 提到錯誤碼的地方也都是同樣這 8 個，判斷是筆誤而非漏列，已改為「八種」；若後續在 `contracts/module_exchange_contract.json` 發現確實存在第 9 個碼，回頭補上並改回九種）：`VALIDATION_ERROR`、`DATA_NOT_FOUND`、`RULE_EVALUATION_FAILED`、`NO_FEASIBLE_ROUTE`、`KNOWLEDGE_RETRIEVAL_FAILED`、`MODEL_INVOCATION_FAILED`、`TIMEOUT`、`INTERNAL_ERROR`。
- 決策留痕：一個 `event_id` 一筆，寫入**整份 `DecisionResult`**（含建議書與簡訊全文）；What-if 結果不得寫入。

## 8. 前端顯示規則

- 只顯示後端給的欄位，不重算。
- `crowd_data_classification = demo` 時人流卡片／圖表標示「Demo Scenario」；`unavailable` 時顯示「資料未提供」，不得顯示猜測值。
- `display_points` 只控制 SVG 位置，不參與任何決策。
- A 級紅、B 級橘、正常青綠；主路線亮綠實線、次路線黃色虛線、封閉路段紅色粗線。
