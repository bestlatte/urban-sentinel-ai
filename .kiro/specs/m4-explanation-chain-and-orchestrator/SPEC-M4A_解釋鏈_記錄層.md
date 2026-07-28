# SPEC-M4A 模組四：解釋鏈記錄層（A4 / DB5）— v2.1

> 依賴：SPEC-00（ActorCode / ToolName / ReasonCode / FindingCode 列舉以 SPEC-00 為唯一來源）。
> 本文件為純確定性層：**不含任何 LLM 呼叫**。LLM 生成見 SPEC-M4B。
> v2.1 變更：列舉改引用 SPEC-00（新增 NOT_IN_ALTERNATIVES、SATURATED_BUT_RETAINED）；agent 欄位改用 ActorCode；What-if 不寫 trace 的邊界明確化；其餘沿用 v2。
> **[2026-07-28 總架構師補註]** `ReasonCode` 已從七值擴充為九值（新增 `UNKNOWN_SEGMENT`、`MISSING_TRAFFIC_SNAPSHOT`，對齊 M2-C 實際會產生的排除情境），本文件下方寫「七值」的地方請理解為「現行 SPEC-00 §3.3 的九值」。

## 1. 目的與設計原則

記錄各確定性模組（P5、R 鏈、A3）與編排層（A2）在處理事件時的每一步判斷，作為模組四「可解釋性」的唯一事實來源。

**記錄與生成分離**：記錄階段零 LLM、決定性、可單元測試；說明文字在需要時才由 M4B 從結構化紀錄生成，LLM 永遠唯讀、不回寫。理由：LLM 轉述存在改寫細節、混淆條款編號的風險，若生成文字被當事實儲存，將無法區分「系統實際依據」與「轉述誤差」。

## 2. 前提假設

- 單一行程執行；多行程分散式寫入不支援（序號機制需集中式時再改）。
- 單一週期 TraceStep 為個位數至十位數（15 路段規模）。
- `input` / `output` / `evidence` 為不透明資料：本模組不解析、不驗證內部結構（鬆耦合）。
- `trace_id` 對應「決策週期」，由 A2 生成並先註冊；一週期可含多條觸發規則（複合事件）。
- **W1 What-if 不呼叫本模組**（SPEC-00 慣例：模擬不入稽核）。

## 3. 資料結構

```
TraceMeta {
  trace_id:      string      // 必填；A2 生成，格式 TR-YYYYMMDD-HHMM-serial（本模組不驗格式，僅驗非空與未重複）
  triggered_by:  string[]    // 必填 ≥1 項；每項符合 `§\d+(-[A-Za-z])?`
  opened_at:     string      // 儲存層指派，ISO 8601
}

TraceStep {
  trace_id:            string          // 必填；須已 open_trace
  sequence_no:         int             // 儲存層原子指派，從 1 遞增；呼叫端不可指定
  parent_seq:          int | null      // 選填；須指向同 trace 已存在序號；DAG 分支歸屬（通常指向 DISPATCH）
  timestamp:           string          // 儲存層寫入當下指派，ISO 8601；呼叫端不可指定
  agent:               ActorCode       // 必填；SPEC-00 §3.1，寫入時驗證
  tool:                ToolName | null // 選填；SPEC-00 §3.2，寫入時驗證
  action:              string          // 必填非空；保留值：SET_FLAG / PLAN / DISPATCH / AGENT_TIMEOUT / CYCLE_SUMMARY
  input:               object          // 必填可空 {}；不透明
  output:              object          // 必填可空 {}；不透明
  sop_ref:             string | null   // 選填；格式 `§\d+(-[a-z])?`
  excluded:            ExcludedItem[]  // 必填可空 []
  findings:            Finding[]       // 必填可空 []
  subject_segment_ids: string[]        // 必填可空 []；每項須為合法路段代碼
  duration_ms:         int | null      // 選填；≥ 0
}

ExcludedItem { segment_id: string（合法路段代碼）,
               reason_code: ReasonCode（SPEC-00 §3.3，九值）,
               reason_detail: string | null（呼叫端固定字串，禁 LLM 生成） }

Finding { finding_code: FindingCode（SPEC-00 §3.4，五值，含 SATURATED_BUT_RETAINED）,
          segment_ids: string[]（可空；每項合法）,
          evidence: object（不透明結構化佐證）,
          detail: string | null（禁 LLM 生成） }
```

### 欄位設計理由（摘要）

- **sequence_no / timestamp 由儲存層指派**：消除並行寫入競爭與呼叫端時鐘不一致；此類錯誤依賴執行時機、難以測試重現。
- **parent_seq**：無此欄位 Trace 只能呈現一維序列，複合事件的平行協作無法還原為 DAG。未用平行時全 null，退化為直線序列，功能不受影響。
- **excluded / findings 分立**：excluded 是「候選為何被刷掉」，findings 是「對方案的發現」（含飽和例外 SATURATED_BUT_RETAINED——該路段未被排除，語意上不能放 excluded）。兩者都結構化，讓 M4B 的追問篩選可精確比對而非關鍵字猜測。
- **路段代碼寫入時 fail-fast**：來源多為程式錯誤（打錯代碼），及早失敗比生成解釋時才發現「查無路段」易除錯。
- **禁 LLM 生成 detail 字串**：維持整份紀錄的事實可靠性（第 1 節原則）。

## 4. 函式契約

### 4.1 open_trace

```
open_trace(trace_id: string, triggered_by: string[]) -> None
```

前置：trace_id 非空且未註冊；triggered_by ≥1 且每項格式合法。違反拋 ValueError。行為：註冊、記 opened_at、初始化序號計數器。重複註冊拋 ValueError。

### 4.2 record_step

```
record_step(trace_id, agent, action, input, output,
            parent_seq=None, tool=None, sop_ref=None,
            excluded=[], findings=[], subject_segment_ids=[],
            duration_ms=None) -> int   # 回傳指派的 sequence_no
```

前置（任一不成立拋 ValueError、不寫入）：trace 已註冊；agent ∈ ActorCode；tool 為 None 或 ∈ ToolName；action 非空；parent_seq 為 None 或指向同 trace 既有序號；sop_ref 格式合法或 None；三處路段代碼皆合法。

行為：驗證 → 取序號 → 指派 timestamp → 寫入 → 回傳序號。明確不做：呼叫 LLM、解析不透明欄位。傳輸機制（同步/佇列）由整合層決定，本文件僅定義行為契約。

## 5. 延伸欄位與安全降級

| 欄位 | 對應延伸功能 | 未實作時的值 | 降級後行為 |
|---|---|---|---|
| findings（X1/X2 類 FindingCode） | Red Team / Simulation | []（或僅含 SATURATED_BUT_RETAINED） | 追問篩選僅比對 subject 與 excluded |
| parent_seq | 平行編排 / DAG | null | 一維序列 |
| subject_segment_ids 多元素 | 連鎖分析 | 單元素 | 等價單值行為 |
| triggered_by 多元素 | 複合事件 | 單元素 | 等價單事件行為 |
| tool | 工具統計 | null | 生成說明時省略 |

原則：欄位宣告成本為零，實作成本才是真的；任何「來不及」只造成功能缺項，不造成資料結構回頭重改。

## 6. 驗收測試（全部決定性）

| # | 情境 | 預期 |
|---|---|---|
| 1 | 同 trace 連續三次 record_step | 回傳 1, 2, 3 |
| 2 | trace_id 空字串 | ValueError，不寫入 |
| 3 | 非法路段代碼（excluded / findings / subject 任一處） | ValueError，不寫入 |
| 4 | 未註冊 trace 寫入 | ValueError |
| 5 | 重複 open_trace | 第二次 ValueError |
| 6 | parent_seq 懸空 | ValueError，不寫入 |
| 7 | agent 不在 ActorCode | ValueError，不寫入 |
| 8 | reason_code 不在九值列舉 | ValueError，不寫入 |
| 9 | finding_code=SATURATED_BUT_RETAINED 且 segment 合法 | 寫入成功（飽和例外可被記錄） |
| 10 | duration_ms 缺漏 | 寫入成功，其他功能不受影響 |
