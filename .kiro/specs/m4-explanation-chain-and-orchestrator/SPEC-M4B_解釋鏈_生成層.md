# SPEC-M4B 模組四：解釋生成層（LLM）— v2.1

> 依賴：SPEC-00、SPEC-M4A（讀取其 TraceMeta / TraceStep）。
> 本層是模組四唯一允許 LLM 參與的部分，且**全部為唯讀轉換**：讀結構化紀錄 → 生成文字，永不回寫。
> v2.1 變更：函式改名 answer_trace_query（原 answer_whatif_query）；範圍界定明確排除前瞻 What-if（歸 W1）；篩選條件納入 findings；其餘沿用 v2。

## 1. 職責與邊界

| 問題類型 | 例子 | 歸屬 |
|---|---|---|
| 回溯追問（查已發生決策） | 「為什麼不走延吉街？」「ETE 怎麼算的？」「市民大道有什麼風險？」 | **本層 answer_trace_query** |
| 前瞻假設（What-if） | 「如果 BL17 到 40,000 會怎樣？」 | W1（SPEC-O3 路由；LLM 解析 → 工具重算 → LLM 敘述；不寫 trace） |

問題分流由 SPEC-O3 §4 的確定性路由負責，本層不做路由。

## 2. resolve_segment_id

```
resolve_segment_id(text: string) -> string | "AMBIGUOUS" | "NOT_FOUND"
```

演算法：取全部路段 name 清單 → 子字串比對 → 恰一個命中回傳其 segment_id；零個回 NOT_FOUND；多個命中採**最長匹配優先**（「信義路五段」優於「信義路」），最長仍並列才回 AMBIGUOUS。

理由：較長名稱通常是較短名稱的更精確版本，優先採用可減少追問往返；只有真正無法判斷時才要求使用者釐清。

## 3. generate_report_explanation

```
generate_report_explanation(trace_id: string) -> string
```

前置：trace 底下至少一筆 TraceStep；否則拋 ValueError（不得回空字串或憑空生成）。

行為（**冪等**）：
1. 快取命中 → 直接回傳，不重複呼叫 LLM
2. 未命中 → 讀 TraceMeta + 全部 TraceStep（依 sequence_no 排序）→ 依第 5 節提示詞契約呼叫 LLM → 存快取 → 回傳

冪等理由：報告會被重複檢視/重試；不冪等會造成重複成本與同一 trace 兩次生成用詞不一致（使用者誤以為系統改變判斷）。

失敗處理：LLM 失敗（逾時/服務錯誤）→ 向呼叫端拋例外，**不得**回傳部分內容或以樣板偽裝成功。由呼叫端（A2 的 EXPLAIN 階段）決定降級：報告該段顯示「決策說明生成失敗，請查閱原始紀錄」+ trace_id。

## 4. answer_trace_query

```
answer_trace_query(trace_id: string, question: string) -> string
```

行為：
1. `resolve_segment_id(question)`：NOT_FOUND → 固定文字「無法識別問題中提及的路段，請確認路段名稱」；AMBIGUOUS → 固定文字「提及的路段名稱有多種可能，請提供更明確的路段全名」。兩者皆**不呼叫 LLM**。
2. 篩選同 trace 紀錄，任一成立即命中：
   - `subject_segment_ids` 含目標路段
   - `excluded[].segment_id` 等於目標路段
   - `findings[].segment_ids` 含目標路段
3. 命中為空 → 固定文字「此路段未列入本次判斷」，**不呼叫 LLM**（無依據時不讓 LLM 自行組織答案）。
4. 命中非空 → 篩選出的紀錄 + 原始問題，依第 5 節契約呼叫 LLM 生成回答。

**不快取**：追問內容不可預測；在「單週期紀錄為個位數至十位數」的規模假設下重複生成成本可忽略，快取的鍵設計/失效複雜度不划算。此決策與規模假設綁定。

失敗處理：LLM 失敗 → 回固定文字「系統暫時無法生成說明，相關原始紀錄如下：」+ 篩選結果原文。**降級為顯示原始資料，永不沉默、永不偽裝。**

## 5. 提示詞契約（兩函式共用，實作不得增減規則）

```
你是交通指揮系統的說明文字生成器。你會收到一組結構化的決策紀錄。
規則：
1. 只能使用提供的紀錄中出現的資訊，不得添加任何未出現的細節。
2. 每一項結論都必須附上對應的 sop_ref。
3. 若紀錄中的欄位不足以回答問題，明確說明「紀錄中未包含此資訊」，不得推測。
4. 使用繁體中文，語氣正式、簡潔。
```

輸入：TraceMeta（含 triggered_by）+ 結構化 TraceStep 清單（JSON）+（僅 answer_trace_query）使用者原始問題。

本契約遵循 SPEC-00 鐵律 1：LLM 只表達，不得改寫事件 ID、級別、路線、ETE、條款編號。

## 6. 驗收測試

| # | 情境 | 預期 |
|---|---|---|
| 1 | 查無路段的追問 | 回「此路段未列入本次判斷」；LLM mock 呼叫次數 0 |
| 2 | 路段名無法識別 | 回「無法識別…」固定文字；LLM 不被呼叫 |
| 3 | 最長匹配 | 問題含「信義路五段」重疊情境 → 回傳五段的代碼 |
| 4 | excluded 命中 | 「為什麼不走延吉街」→ 命中 R5 紀錄 → 回答含 CAPACITY_INSUFFICIENT 對應敘述與 §2-a |
| 5 | findings 命中 | 「市民大道有什麼風險」→ 命中 SATURATED_BUT_RETAINED 或 X2 finding 的紀錄 |
| 6 | 報告冪等 | 連續兩次 generate → 第二次 LLM 不被呼叫、字串相同 |
| 7 | 報告生成於空 trace | ValueError |
| 8 | LLM 失敗降級（追問） | 回固定前綴 + 原始紀錄 JSON；不拋出 |
| 9 | LLM 失敗（報告） | 拋例外給呼叫端；不回傳部分內容 |
