# 官方模組四 — ETE、建議書與通報 | Requirements

> 狀態：✅ 已確認（總架構師撰寫）
> 契約模組代碼：`decision_reporting`（依 `.kiro/steering/01-module-boundaries.md` 定義）
> 擁有檔案（可寫）：`src/reporting.py`
> 唯讀：`src/models.py`（型別定義處，M5擁有）、`data/**`（透過 M1 產出的 `NormalizedDataBundle`，不得直接讀 `data/`）

> **命名提醒**：本文件是 `01-module-boundaries.md` 表格中真正的「M4」（`decision_reporting`），負責 ETE 計算與 C1-C4 報告/通報生成。這**不是**解釋鏈（那是 `.kiro/specs/m4-explanation-chain-and-orchestrator/`，命名雖然都帶「模組四」但範圍不同，兩者互不重疊、都要做）。

---

## 一、元件定位

本模組是「把已經算好的事實，變成給人看的文字」的地方。它是 `01-module-boundaries.md` 三層決策職責中「算答案」與「寫文字」的交界：

- **A3（ETE計算）**：確定性公式，零 LLM。
- **C1~C4（建議書/號誌/聯動/簡訊生成）**：LLM 生成，但**只能表達 A3 與 M2(routing)/M1(rules) 算出的事實，不得改寫事件ID、位置、級別、路線、ETE數值或SOP條款編號**（鐵律，見 `01-module-boundaries.md` 第3節）。

被 M5（Orchestrator）呼叫，透過 `ModuleGateway.calculate_ete()` 與 `ModuleGateway.generate_report()` 兩個邊界函式對外提供服務（介面定義見 M5 spec，本文件定義其內部行為）。

---

## 二、A3：ETE 計算（確定性）

```
calculate_ete(incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate
```

### 公式（唯一來源，不得在其他模組重複實作或修改）

```
ETE_minutes = base_clearance + max(0, (average_saturation - 0.5) * 60)

base_clearance：
  severity == "Critical" → 60
  severity == "High"     → 40
  severity == "Medium"   → 20
  severity == "Low"      → 20（沿用 Medium 值，SOP 原文未定義 Low，取最保守但非零值）

average_saturation：受影響路段（取 incident.affected_road，若為 null 則取 affected_segment 中 RD_ 開頭者）
  在 incident.timestamp 的 as-of 飽和度（呼叫 M1 的 get_saturation）。
  若受影響路段不只一條（例如複合事件涉及多路段），取平均值。
```

### 輸出

```
EteEstimate {
  minutes:        int
  recovery_at:    string   // incident.timestamp + minutes，格式 "YYYY-MM-DD HH:MM"
  formula:        string   // 固定文字，附上實際代入數值，供解釋鏈引用，例：
                            // "60 + max(0,(1.0-0.5)*60) = 90"
  base_clearance: int
  average_saturation: float
}
```

### 黃金驗收值（唯一依據，不得因程式改版而變動）

| 事件 | severity | average_saturation | ETE | recovery_at |
|---|---|---:|---:|---|
| `TPE_2026_ACC_001` | Critical | 1.0 | **90 分** | 2026-05-20 23:40 |
| `TPE_2026_EVT_002` | High | — | **70 分** | 依資料集實算 |
| `TPE_2026_EVT_003` | Medium | 0.85 | **41 分** | 依資料集實算 |

算出的數字與上表不符時，先檢查 as-of join 是否抓錯時間點、`severity` 是否誤植為 `traffic_level`（A/B），不要改公式本身。

---

## 三、C1~C4：報告與通報生成（LLM，唯讀轉換）

```
generate_report(
  incident: Incident,
  sensing: SensingResult,
  route_plan: RoutePlan | None,
  ete: EteEstimate,
  advisory: BedrockAdvisory | None,
) -> tuple[str, Notification | None]
```

回傳值：`(交控建議書全文, 多語簡訊物件)`。第二個回傳值是**單一物件**（[2026-07-28更正] 原寫 `list[Notification]`，已改為單一物件，對齊 `SPEC-O3` `DecisionResult.notifications` 的形狀），結構為 `{zh: string, en?: string, ja?: string, ko?: string}`；SOP-6 未觸發時只有 `zh`，其餘語言鍵不存在或為 `null`。`Notification` 結構定義於 `src/models.py`（M5擁有），須跟這個形狀一致。

### 3.1 輸入邊界（鐵律具體化）

C1~C4 的 prompt 組裝時，以下欄位由呼叫端（本模組）以確定性方式從 `incident`／`sensing`／`route_plan`／`ete` 直接取值並注入 prompt，**LLM 不得自行產生或變更**：

```
event_id, location, type, status, severity
traffic_level（A/B）
primary_route / secondary_route / exclusion_reasons（來自 route_plan）
ete.minutes / ete.recovery_at
命中的 SOP 條款編號（來自 sensing.rule_hits 的 clause_id）
affected_intersection_count（SOP-5 用；來自 routing.py 的 COUNT_INTERSECTIONS，已含 × 2 換算，見 3.4）
```

LLM 只負責：把上述事實組織成通順的段落、決定用詞語氣、產生跨系統聯動的建議措辭、把中文簡訊翻譯成其他語言。

### 3.2 C1 交控建議書 — 應涵蓋內容

1. **事件辨識**：`event_id`、事件描述、命中的 SOP 條款編號（例：SOP-1、SOP-2、SOP-7）
2. **交通分級判定**：A級/B級/其他，引用 `sensing` 的飽和度數值作為依據
3. **替代路徑建議**：`route_plan.primary`、`route_plan.secondary`，並列出 `route_plan.excluded` 每一項的 `reason_code` 轉譯成人話（例：`CAPACITY_INSUFFICIENT` → 「容量不足（600 < 1000）」）
4. **號誌調整建議**（即 C2 內容，併入 C1 全文或獨立段落皆可，見 3.3）
5. **跨系統聯動**（即 C3 內容，僅命中 SOP-3 或 SOP-5 時才出現，見 3.4）

### 3.3 C2 號誌配時建議

- 僅當命中 SOP-1（B級以上）時產出。
- 內容：受影響路段（觸發路段的 `alternatives`）、配時調整比例（固定 **+25%** 綠燈延長，SOP §1/§2 明文）、調整時段（以 `incident.timestamp` 起算，持續至 `ete.recovery_at`）。
- 範例輸出格式：「仁愛路四段綠燈時間增加 25%，調整期間為 22:10 至 23:40。」

### 3.4 C3 跨系統聯動建議

- 觸發條件：命中 SOP-3（人流，捷運分流）或 SOP-5（號誌故障）。
- SOP-3 命中：建議北捷「過站不停」、通知公車處調度接駁專車、引導群眾步行至替代站點（固定建議 `BS_MRT_BL18`，依 SOP §3 原文）。
- SOP-5 命中：警力人力 = 受影響路口數 × 2 人，附估計持續時間（= `ete.minutes`）。[2026-07-28更正] 「受影響路口數」與「× 2」這個乘法都由呼叫端（orchestrator）呼叫 `routing.py` 的 `COUNT_INTERSECTIONS` 工具（`SPEC-00` §3.2）算好，`警力人力` 這個最終數字當成事實欄位直接注入 C3 prompt，跟 `ete.minutes`／`route_plan.primary` 等欄位同一套處理方式——LLM 只負責把這個已經算好的數字組織成人話敘述，不得自己計算或臆測路口數或做乘法（見 3.1 輸入邊界原則）。

### 3.5 C4 多語簡訊

```
觸發判定：sensing.rule_hits 中是否含 SOP-6（漫遊率 >= 0.30 的站點命中）
  未觸發 → 只產出中文簡訊（Notification.zh 有值，en/ja/ko 為 null）
  觸發   → 至少中文＋英文；日文/韓文為加分項，能力允許時一併產出
```

- 內容涵蓋：事故位置、改道指引（`route_plan.primary`）、預計延誤時間（`ete.minutes`）、求援或避開提醒。
- **可讀性限制**：適合 CMS 電子看板與手機簡訊呈現，單則簡訊建議不超過 100 字（中文）／160 字元（英文），避免冗長技術術語（不得出現 `segment_id`、`reason_code` 等內部代碼，一律轉成路名與白話說明）。
- 時間格式統一 `YYYY-MM-DD HH:MM`（SOP §6 規定）。

### 3.6 提示詞契約（C1~C4 共用，實作不得增減規則）

```
你是交通指揮系統的報告生成器。你會收到一組已經確定的事實資料（事件、分級、路徑、ETE、SOP條款）。
規則：
1. 只能使用提供的事實資料，不得添加、推測或改寫任何數字、路段名稱、SOP條款編號。
2. 每一項結論都必須可追溯到輸入的事實欄位。
3. 語氣正式、簡潔，避免冗長技術術語；C4簡訊需適合一般民眾閱讀。
4. 使用繁體中文為主；C4觸發多語時，各語言版本內容須語意一致，不得增減資訊。
```

### 3.7 失敗處理

- C1（含併入的 C2/C3）生成失敗（LLM逾時/服務錯誤）→ `generate_report()` 第一個回傳值為 `null`；呼叫端（orchestrator）把 `"C1_FAILED"` 加進 `DecisionResult.degraded`（[2026-07-28更正] 欄位名與代碼對齊 `SPEC-O3` §3 的 `degraded: string[]` 慣例，不是本模組自己發明欄位名）。
- C4 生成失敗 → 第二個回傳值為 `null`，呼叫端加入 `"C4_FAILED"`。
- **不得**因單一生成項目失敗導致整個 `generate_report()` 拋出例外中斷——已經算好的 `route_plan`／`ete` 等事實資料仍要能送到前端，只是文字說明的部分標示「生成失敗，請查閱原始數據」。此行為與 `01-module-boundaries.md` 第5節「降級規則：永不沉默」一致。

---

## 四、驗收測試

| # | 情境 | 預期 |
|---|---|---|
| 1 | ACC_001 ETE 計算 | 90 分，恢復 2026-05-20 23:40 |
| 2 | EVT_003 ETE 計算 | 41 分 |
| 3 | severity 缺漏 | 拋 `VALIDATION_ERROR`，不得預設為某個值悄悄算下去 |
| 4 | C1 不得出現內部代碼 | 生成文字中掃描不到 `reason_code`／`segment_id` 等原始欄位名，只有路段中文名 |
| 5 | SOP-6 未觸發時 C4 | `Notification.en` 為 `null`，只有 `zh` |
| 6 | SOP-6 觸發時 C4 | `Notification.zh` 與 `en` 皆非空，且事故位置/ETE數值於兩語言版本一致 |
| 7 | LLM 生成失敗降級 | `generate_report()` 正常回傳（不拋例外），對應欄位標示降級 |
| 8 | 事實欄位不被 LLM 改動 | 對同一組輸入呼叫兩次，生成文字用詞可以不同，但其中出現的路段名/ETE數值/SOP編號必須逐字相同 |

## 五、Definition of Done

- [ ] A3 公式完成，三筆黃金事件驗收值全部通過
- [ ] C1~C4 生成邏輯完成，事實欄位由呼叫端注入、LLM不改寫
- [ ] SOP-6 多語觸發判定正確
- [ ] 失敗降級不拋出例外，符合「永不沉默」原則
- [ ] 不依賴其他模組的內部實作（只透過 M1/M2 產出的型別物件）
