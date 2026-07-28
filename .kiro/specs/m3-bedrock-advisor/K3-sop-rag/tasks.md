# K3 — SOP RAG 檢索服務 | Tasks

> 前置文件：`specs/K3-sop-rag/requirements.md`、`specs/K3-sop-rag/design.md`
> 預估總工時：3~4 小時（含 AWS 設定）

> **[2026-07-28 總架構師補註]** design.md 已修正兩處，本文件沿用舊寫法，理解時請套用修正版：`src/rag/` 一律讀作 `src/bedrock_service/`；`SOPQueryResult.source` 欄位一律讀作 `retrieval_source`，且值多一種 `"local_fallback"`。
>
> Task 4 的 `scripts/generate_sop_index_files.py`／`scripts/upload_sop_to_s3.py` 與衍生出的 `data/sop-index/*.txt`，都不在 `00-tech-stack.md` §3 固定結構內（`scripts/` 未列出；`data/` 固定結構只寫「五個 canonical JSON + display_geometry.json」）。理由：這是一次性的 KB 建置工具與其衍生索引檔，不是應用程式讀取路徑的一部分（跑完 Task 4/5 之後，正式流程只透過 Bedrock KB ID 查詢，不會再讀這些 txt 檔），視為建置期間的輔助產物，不算「新增模組檔」，不影響 Kiro 生成 `src/` 內的正式程式碼。

---

## Task 1：建立檔案結構與資料預載

**做什麼：** 建立 `src/rag/` 資料夾，寫 `sop_data.py` 把 SOP JSON 載入記憶體。

**具體步驟：**
1. 建立 `src/rag/__init__.py`、`sop_data.py`
2. 在 `sop_data.py` 實作 `_load_sop_data()` 函式，讀取 `data/emergency_traffic_sop.json`
3. 定義 `SOPSection` 和 `SOPQueryResult` 資料結構（dataclass）
4. 確認 `SOP_DATA` 能正確載入 7 個 section

**完成標準：** 跑一個簡單的 print test，能印出 7 條 SOP 的 title。

---

## Task 2：實作本機關鍵字比對（local fallback）

**做什麼：** 寫 `local_fallback.py`，實作不依賴雲端的 SOP 查詢。

**具體步驟：**
1. 定義 `KEYWORD_MAP`（7 條各自的關鍵字清單）
2. 實作 `_query_local(question: str) -> list[SOPSection]`
3. 比對邏輯：計算命中數 / 關鍵字總數作為 score，取前 3、過濾低於閾值的

**完成標準：**
- 輸入「路面塌陷封閉」→ 回傳第 2 條（score 最高）
- 輸入「ETE 怎麼算」→ 回傳第 7 條
- 輸入「今天天氣如何」→ 回傳空 `[]`

---

## Task 3：實作主入口與模式切換

**做什麼：** 寫 `sop_retriever.py`，實作對外的 `query_sop()` function 和 `USE_BEDROCK` 切換。

**具體步驟：**
1. 讀取環境變數 `USE_BEDROCK`
2. 實作 `query_sop(question)` 主函式
3. `USE_BEDROCK=false` 時呼叫 `_query_local()`
4. `USE_BEDROCK=true` 時先留一個 placeholder（return 空結果 + print "bedrock not yet implemented"）
5. 加上 try/except：Bedrock 呼叫失敗時自動退化到 local

**完成標準：** 設定 `USE_BEDROCK=false`，呼叫 `query_sop("BL17 人數超標")` 能正確回傳第 3 條。

---

## Task 4：衍生 SOP 索引文件並上傳 S3

**做什麼：** 寫一個 script，把 JSON 的 7 個 section 各自輸出成 .txt 檔，然後上傳 S3。

**具體步驟：**
1. 建立 `scripts/generate_sop_index_files.py`
2. 讀取 `data/emergency_traffic_sop.json`，產生 7 個 txt 檔到 `data/sop-index/` 資料夾
   - 檔名：`SOP-1-交通擁塞級別判定.txt` ... `SOP-7-預計恢復時間ETE計算.txt`
   - 內容格式：`SOP 第 N 條：{title}\n\n{content}`
3. 建立 `scripts/upload_sop_to_s3.py`，用 boto3 把 `data/sop-index/*.txt` 上傳到 `s3://{S3_DATA_BUCKET}/sop-index/`

**完成標準：** S3 bucket 裡出現 7 個 txt 檔案。

> ⚠️ 此 Task 需要 AWS 憑證已設定完成（見 `AWS服務選型建議.md` 0.2~0.3 節）。如果 AWS 還沒通，先跳過此 Task，不影響 Task 2/3 的開發。

---

## Task 5：建立 Bedrock Knowledge Base

**做什麼：** 在 AWS Console 建立 KB，向量儲存選 S3 Vectors，指向 S3 上的 SOP 檔案。

**具體步驟：**
1. 進 AWS Console → Bedrock → Knowledge Bases → Create
2. Data source 選 S3，指向 `s3://{S3_DATA_BUCKET}/sop-index/`
3. 向量儲存選 S3 Vectors
4. Embedding model 選預設（Titan Embeddings 或 KB 自動選）
5. 建立完成後，點 **Sync** 同步
6. 等狀態變為 Ready
7. 記下 `Knowledge Base ID`，填入 `.env` 的 `BEDROCK_KNOWLEDGE_BASE_ID`

**完成標準：** 在 Console 的 KB 測試介面，輸入「路面塌陷」能回傳第 2 條相關內容。

> ⚠️ 此 Task 由負責 AWS 的組員（成員 D）協助執行。你只需要提供 Task 4 產出的 txt 檔。

---

## Task 6：實作 Bedrock KB 查詢封裝

**做什麼：** 寫 `bedrock_kb.py`，實作真正的 Bedrock Retrieve API 呼叫。

**具體步驟：**
1. 用 boto3 的 `bedrock-agent-runtime` client 呼叫 `retrieve()`
2. 從回傳結果解析 `section_number`（由索引文件的開頭格式判斷）
3. 用解析到的 section_number 去 `SOP_DATA` 取完整原文
4. 組裝成 `SOPSection` 回傳

**完成標準：**
- 設定 `USE_BEDROCK=true`
- 呼叫 `query_sop("號誌故障怎麼處理")` → 回傳第 5 條完整原文
- `content` 與 JSON 原文完全一致（字串比對通過）

---

## Task 7：註冊為 Strands Agent Tool

**做什麼：** 把 `query_sop` 包裝成 `@tool`，讓 A2 和 W1 的 Agent 可以呼叫。

**具體步驟：**
1. 在 `sop_retriever.py`（或另建 `sop_tool.py`）加上 `@tool` 裝飾器
2. 回傳格式轉為 dict（Strands tool 需要 JSON serializable）
3. 寫 docstring 讓 Agent 知道何時該呼叫此 tool

**完成標準：** 在一個測試 Agent 中，問「BL17 超過 25000 要怎麼處理」，Agent 會自動呼叫 `query_sop` 並拿到第 3 條。

> ⚠️ 此 Task 依賴 Strands SDK 已安裝。如果還沒裝，先跳過，不影響 Task 1~6。

---

## Task 8：端到端測試

**做什麼：** 驗證整條路徑都通。

**測試案例：**

| # | 查詢 | 預期回傳的 section_number | 模式 |
|---|------|--------------------------|------|
| 1 | 「路面塌陷、Closed、Critical」 | 2 | both |
| 2 | 「BL17 人數超過 25000」 | 3 | both |
| 3 | 「號誌失效」 | 5 | both |
| 4 | 「漫遊比率超過 30%」 | 6 | both |
| 5 | 「ETE 計算公式」 | 7 | both |
| 6 | 「今天天氣好嗎」 | [] (空) | both |
| 7 | 「飽和度 0.95 要觸發什麼」 | 1 (+ 可能 2) | both |

**完成標準：** 7 個案例在雲端模式和本機模式都通過。

---

## 執行順序建議

```
可立即開始（不需等 AWS）：
  Task 1 → Task 2 → Task 3

需要 AWS 憑證：
  Task 4 → Task 5 → Task 6

需要 Strands SDK：
  Task 7

全部完成後：
  Task 8
```

不被 AWS 擋住的開發路線：**先做 Task 1~3**，本機模式就能完整跑起來。AWS 好了再接 4~6。
