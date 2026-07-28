# M1 — 資料感知與規則 | Requirements

> 狀態：✅ 已確認（總架構師撰寫，依 `.kiro/steering/01-module-boundaries.md`、`02-data-contract.md` 為唯一依據）
> 契約模組代碼：`data_ingestion`、`sensing_rules`
> 擁有檔案（可寫）：`src/loaders.py`、`src/rules.py`、`data_manifest.md`
> 唯讀：`data/**`（只有 M1 可以讀原始 JSON/CSV，其他模組一律用 M1 產出的 `NormalizedDataBundle`）

本文件是整條資料流的起點：`data/*.json|*.csv → M1(loaders) → NormalizedDataBundle → M1(rules) → SensingResult`。其他模組（M2/M3/M4/M5）不得重算本文件定義的任何數值或門檻。

---

## 一、元件定位

M1 分兩層：

- **D1-D4（`loaders.py`）**：把五個原始資料檔讀進來、校驗格式、正規化時間與單位，組成 `NormalizedDataBundle`。純資料處理，不做判斷。
- **P1-P5（`rules.py`）**：拿 `NormalizedDataBundle` 算出三個感知指標、比對 SOP 門檻、判定交通等級。純規則引擎，**零 LLM**。

---

## 二、資料來源與已知格式陷阱

### 2.1 五個 canonical 檔案

| 檔案 | 格式 | 對應 loader |
|---|---|---|
| `data/city_traffic_flow.json` | JSON array，112 筆 | D1 |
| `data/signaling_crowd_density.csv` | **CSV**（非JSON），36 筆（[2026-07-28再更正] 原寫37筆，`wc -l` 把標題列算進去的計算失誤），真實資料 | D1 |
| `data/road_network_topology.json` | JSON array，15 筆 | D1 |
| `data/live_incidents.json` | JSON array，3 筆 | D1（供 D4 監聽用） |
| `data/emergency_traffic_sop.json` | JSON object，7 sections | D1 |

### 2.2 原始欄位對照與正規化規則（D2/D3 責任，P 系列不得再轉換）

**`city_traffic_flow.json`**（已是 PascalCase，需轉 snake_case）：

```
Timestamp → timestamp（解析後輸出 ISO 8601 +08:00）
Segment_ID → segment_id
Road_Name → road_name
Avg_Speed → avg_speed（可為 null，null 代表缺資料，不等於 0）
Vehicle_Count → vehicle_count
Saturation_Score → saturation_score（已是 0.0~1.0，不轉換）
Lane_Status → lane_status
```

**`signaling_crowd_density.csv`**（真實資料，2026-07-28 由主辦方補齊，欄位名與先前模擬版本不同，**必須依此表**，不得沿用舊模擬版欄位名）：

```
Timestamp → timestamp（解析後輸出 ISO 8601 +08:00；注意本檔沒有秒，格式為 "YYYY-MM-DD HH:MM"）
BS_ID → station_id
Location_Name → station_name
User_Count → user_count
Stay_Time_Avg → stay_time_avg_minutes（新欄位，供選用，非必要判斷依據）
Growth_Rate → growth_rate（已是小數率，**不可再除以或乘以任何倍數**）
Roaming_User_Pct → roaming_user_pct
  【關鍵】原始值是「帶 % 符號的字串」（例如 "10%"、"45%"），
  正規化步驟：先移除 "%" 字元 → 轉成數字 → 除以 100。
  例："40%" → 40 → 0.40。
  這跟舊模擬版本（數字型態、無 % 符號，如 32.0）的處理方式不同，
  loader 必須能同時正確處理「字串帶%」與「純數字」兩種輸入格式，
  以 `isinstance` 或 regex 判斷後分流處理，不得假設輸入一定是某一種格式。
本檔**沒有** Crowd_Status、Sample_Interval_Minutes、Is_Simulated 欄位（因為是真實資料）。
  is_simulated 固定輸出 false。
```

**`road_network_topology.json`**（已是 snake_case，直接載入，不需欄位映射）：

```
segment_id, name, flow_direction, intersections[], capacity_vph, alternatives[], nearby_stations[]
```

- `alternatives` 為單向建議，不可假設對稱，不可據此做對稱性圖搜索。
- `nearby_stations: []` 是合法值（周邊無收錄基地台），不是缺漏，不可自行補值。
- `intersections` 已依「上游→下游」排序，供 SOP §2 上游分流判定使用。

**`live_incidents.json`**（已是 snake_case，直接載入）：

```
event_id, type, location, affected_segment, affected_road(可為null), status, severity, description, timestamp
```

**`emergency_traffic_sop.json`**：

```
title, sections: [{section_number, title, content}]
→ 映射為 SopClause { clause_id: f"SOP-{section_number}", title, content }
```

---

## 三、D1-D4 函式契約

### D1：五資料源載入

```
load_data() -> NormalizedDataBundle
```

- 依序讀取五個檔案；`signaling_crowd_density.csv` 用標準 CSV parser（`csv.DictReader` 或 `pandas.read_csv`），其餘用 `json.load`。
- 任一檔案不存在或格式無法解析 → 拋 `DATA_NOT_FOUND` 例外，不得回傳部分資料靜默繼續。

### D2：Schema 校驗與欄位映射

- 依第二節映射表逐筆轉換欄位名稱與型別。
- 逐筆檢查必填欄位是否存在；缺漏必填欄位的單筆記錄跳過並記錄 `warnings`（不中斷整批載入），格式參考 M2-A 的驗證錯誤碼慣例。
- `road_network_topology.json` 額外驗證：`alternatives[]` 內的 segment_id 必須存在於同一批路網資料中；`intersections[]` 內的名稱若在資料集中查無對應 `name`（例如「正氣橋」等外部交會點），只記 warning，不中斷載入。

### D3：時間與單位正規化

- 全部 `timestamp` 欄位輸出 `YYYY-MM-DDTHH:MM:SS+08:00`（Asia/Taipei）。
- `roaming_user_pct` 依第二節規則轉換為 0.0~1.0 小數。
- `growth_rate` 維持原值，不做任何轉換。
- 正規化完成後的資料，下游（P系列、M2、M3、M4、M5）看到的 `roaming_user_pct` 與 `saturation_score` 一律是 `0.0~1.0` 範圍的小數，不得再出現百分比字串或百分點數值。

### D4：事件注入監聽器

```
on_incident_injected(event: dict) -> Incident
```

- 接收單筆事件（結構同 `live_incidents.json` 單筆），依第二節映射轉換、驗證欄位（`affected_segment`／`affected_road` 至少一項需對應到合法路段或站點 ID）。
- 驗證失敗拋 `VALIDATION_ERROR`，不建立 `Incident` 物件。
- 本函式只負責「驗證＋轉換」，**不寫入任何儲存、不觸發後續流程**——觸發後續分類與編排是 M4 Orchestrator（`SPEC-O1` OPEN 階段）的責任，D4 只是它呼叫的前置轉換工具。

---

## 四、NormalizedDataBundle 結構

```
NormalizedDataBundle {
  traffic_samples:   TrafficSample[]     // 來自 city_traffic_flow.json，D2/D3 正規化後
  crowd_samples:      CrowdSample[]       // 來自 signaling_crowd_density.csv，D2/D3 正規化後
  road_segments:      RoadSegment[]       // 來自 road_network_topology.json
  sop_clauses:        SopClause[]         // 來自 emergency_traffic_sop.json，7 筆
  loaded_at:          string              // ISO 8601 +08:00，本次載入時間
  warnings:           string[]            // D2 驗證過程產生的非致命警告
}

TrafficSample { timestamp, segment_id, road_name, avg_speed, vehicle_count, saturation_score, lane_status }
CrowdSample   { timestamp, station_id, station_name, user_count, stay_time_avg_minutes, growth_rate, roaming_user_pct, is_simulated: false }
```

（`RoadSegment`、`SopClause`、`Incident` 欄位定義見 `contracts/module_exchange_contract.json`，由 M5 的 `src/models.py` 統一定義，M1 只負責產出符合該定義的資料，不重複定義型別。）

---

## 五、P1-P5 函式契約

### P1：飽和度監測

```
get_saturation(bundle: NormalizedDataBundle, segment_id: str, as_of: str) -> float | None
```

- 取 `traffic_samples` 中 `segment_id` 相符、且 `timestamp <= as_of` 的**最近一筆**（as-of join，不做插值，不使用 as_of 之後的資料）。
- 查無資料回傳 `None`（呼叫端須自行處理「缺快照」情境，不得當作 0）。

### P2：人流成長率

```
get_growth_rate(bundle: NormalizedDataBundle, station_id: str, as_of: str) -> float | None
```

- 同樣採 as-of join；`crowd_samples` 的 `growth_rate` 已是正規化後的小數率，直接回傳，不再計算或轉換。

### P3：漫遊比率

```
get_roaming_ratio(bundle: NormalizedDataBundle, station_id: str, as_of: str) -> float | None
```

- 同樣採 as-of join；回傳已正規化（0.0~1.0）的 `roaming_user_pct`。

### P4：SOP 規則引擎（門檻 → 條款 → 動作映射）

```
evaluate_rules(bundle: NormalizedDataBundle, incident: Incident | None = None) -> SensingResult
```

門檻值（唯一來源，其他模組不得另訂）：

```
SOP-1（交通擁塞級別，適用全部 15 路段，任一路段皆可觸發）：
  saturation_score >= 0.95 → A 級
  0.85 <= saturation_score < 0.95 → B 級
  【重要】此分級適用「全部 15 路段」，不限定特定路段——任何路段達到 B/A 級
  都必須產生 RuleHit 並可觸發 F2 異常彈窗，這是命題模組1的核心要求。

SOP-1 城市應變觸發（僅此為特定路段限定，是 SOP-1 分級之上的「額外」動作）：
  觸發路段限定：RD_TPE_001（忠孝東路四段）、RD_TPE_002（光復南路）
  這兩條路段之一達 B 級以上時，額外標記 RuleHit.action_flag = "CITY_RESPONSE"，
  下游（reporting.py 的 C2）依此決定是否產出「啟動長綠燈時制」的號誌建議；
  其他 13 條路段達 B/A 級時，正常產生分級 RuleHit，但不帶此 flag，
  也不觸發「長綠燈時制」這個城市級應變動作——這只是動作範圍的差異，
  分級判定本身（A/B級）不因路段而有任何不同。

SOP-3（捷運與接駁分流）：
  station_id == "BS_MRT_BL17" 且 (growth_rate > 0.30 或 user_count > 25000)

SOP-4（大巨蛋散場啟動）：
  station_id == "BS_TPE_DOME" 且
  歷史峰值 user_count（僅計入 timestamp <= as_of 的記錄，不得使用 as_of 之後的資料計算「歷史」峰值）>= 30000 且
  當前（as_of 那筆）growth_rate <= -0.20
  → 觸發時同時追加 SOP-3 連動（P4 內部直接標記，不交給下游判斷）

SOP-6（數位通報與多語化）：
  任一站點 roaming_user_pct >= 0.30
  → 產出 flag，不產生獨立 RuleHit 動作項（由 M4 Orchestrator 的 SPEC-O1 FLAGS 階段消費）
```

- 命中的每條規則輸出一筆 `RuleHit { clause_id, segment_id_or_station_id, evidence: {實際數值} }`。
- 若傳入 `incident`，額外比對 SOP-2（車禍路障，`status ∈ {Closed,Blocked,Restricted}` 且 `severity ∈ {High,Critical}` 且 `affected_segment` 以 `RD_` 開頭）與 SOP-5（`type == "Power_Failure"`）——這兩條的比對邏輯是 P4 的責任，但實際路徑規劃與人力派遣分別交給 M2（路網）與 M4 Orchestrator（SPEC-O2 靜態表 §5 分支）處理，P4 只負責判定「這條規則有沒有命中」。

### P5：事件級別判定

```
determine_level(rule_hits: RuleHit[]) -> "A" | "B" | None
```

- 純粹從 P4 輸出的 `RuleHit` 中挑出 SOP-1 相關命中，回傳對應等級；無命中回傳 `None`。
- `severity` 欄位（Critical/High/Medium/Low）用於事件本身的嚴重度分類，**不得**與 `traffic_level`（A/B）混用或互相推導——兩者是獨立欄位。

---

## 六、驗收測試（全部決定性，可用真實資料直接斷言）

| # | 情境 | 輸入 | 預期 |
|---|---|---|---|
| 1 | 真實 CSV 漫遊率解析 | `Roaming_User_Pct = "40%"` | 正規化後 `roaming_user_pct = 0.40` |
| 2 | 真實 CSV 漫遊率解析（邊界） | `Roaming_User_Pct = "5%"` | 正規化後 `roaming_user_pct = 0.05` |
| 3 | Growth_Rate 不重複轉換 | `Growth_Rate = -0.31` | 正規化後仍為 `-0.31`，非 `-31` 或 `-0.0031` |
| 4 | as-of join 正確性 | 查詢 `BS_TPE_101` 在 `2026-05-20 22:10` 的漫遊率 | 回傳 `20:00` 那筆（`0.40`），不得回傳 `22:15` 那筆（未來資料） |
| 5 | SOP-6 黃金值（2026-07-28 更正後） | as-of `22:00` | `BS_TPE_101(0.40)`、`BS_XY_ATT(0.30)` 命中；`BS_TPE_DOME` 不命中（真實漫遊率僅 0.05） |
| 6 | SOP-1 黃金值 | `RD_TPE_002` at `22:10` | `saturation_score = 1.0` → A 級，且帶 `CITY_RESPONSE` flag |
| 6b | SOP-1 分級不限定路段（回歸測試，防止重蹈「限定路段」誤判） | `RD_TPE_003`（非城市應變觸發路段）at `22:00`，`saturation_score = 0.95` | 仍正確判為 A 級並產生 RuleHit，但**不帶** `CITY_RESPONSE` flag |
| 7 | SOP-4 黃金值 | `BS_TPE_DOME` at `22:00` | 峰值 `40000`（19:00）、當前 `22000`、growth `-0.31` → 觸發，且追加 SOP-3 |
| 8 | 缺值不當零 | `Avg_Speed = null` | `get_saturation` 等函式不得將 `null` 視為 `0` 處理 |
| 9 | 外部交會點容錯 | `intersections` 含「正氣橋」 | 記 warning，不中斷載入 |
| 10 | 相同輸入相同輸出 | 連續呼叫兩次 `evaluate_rules` | 結果完全一致（無隨機性） |

---

## 七、Definition of Done

- [ ] D1~D4 完成，兩種資料格式（JSON + CSV）皆可正確載入
- [ ] `signaling_crowd_density.csv` 的 `%` 字串解析與 `city_traffic_flow.json` 的欄位映射皆通過單元測試
- [ ] P1~P5 完成，且全部驗收測試（含真實資料黃金值）通過
- [ ] `data_manifest.md` 產出，內容至少包含第二節的欄位對照表
- [ ] 不依賴任何外部模組、LLM 或雲端服務
