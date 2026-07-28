# K3 — SOP RAG 檢索服務 | Requirements

> 狀態：✅ 已確認
> 負責人：模組三
> 相依：DB4（SOP 向量庫）、Bedrock Knowledge Bases、S3
> 被呼叫者：A2（Orchestrator）、W1（What-if 問答 LLM）

---

## 一、元件定位

K3 是一個「SOP 條款查詢服務」。系統中任何需要知道「SOP 怎麼說」的元件，都透過 K3 來取得 SOP 原文。K3 本身不做判定、不做推理，只負責「把最相關的條款找出來，原文回傳」。

---

## 二、功能需求

### REQ-1：接收自然語言查詢，回傳相關 SOP 條款

- 輸入：一段自然語言問題（中文）
- 輸出：最相關的前 3 條 SOP 條款，每條包含：
  - `section_number`（第幾條，1~7）
  - `title`（條款標題）
  - `content`（條款完整原文，不改寫、不摘要、不省略）
  - `relevance_score`（0~1 之間的相關性分數）
- 回傳結果依 relevance_score 降序排列

### REQ-2：保證原文完整性

- K3 回傳的 content 必須是 SOP 原文的完整複製，不做任何改寫、摘要或截斷。
- 這是為了讓呼叫者（A2 / W1）能精準引用條款，避免幻覺。

### REQ-3：無相關結果時的明確回應

- 當所有候選條款的 relevance_score 都低於閾值時，K3 應回傳一個明確的「未找到相關條款」訊號（例如空陣列 + 狀態碼標示），而非硬湊低相關的結果。
- 這讓 W1 可以明確告訴使用者「SOP 未涵蓋此情境」。

### REQ-4：回應速度

- K3 的查詢延遲應在 2 秒以內完成（SOP 僅 7 條，不會是瓶頸）。
- 不得成為 60 秒 SLA 的瓶頸。

### REQ-5：不做快取

- SOP 內容固定不變動，且資料量極小（7 條），查詢延遲本身已極低。
- 不實作快取機制，避免增加複雜度和出錯點。

---

## 三、實作模式（雙軌）

### 雲端模式（`USE_BEDROCK=true`，正式 Demo）

- SOP JSON 的 7 個 section 衍生成索引文件（每條一份），上傳至 Amazon S3。
- 建立 Bedrock Knowledge Base，向量儲存選 S3 Vectors。
- K3 包裝一層 Bedrock KB 的 Retrieve API 呼叫。
- relevance_score 直接取用 Bedrock KB 回傳的分數。

### 本機保底模式（`USE_BEDROCK=false`，離線/斷線時）

- 直接讀取 `data/emergency_traffic_sop.json` 的 7 個 section。
- 使用簡單的關鍵字比對（title + content 比對查詢詞），回傳最匹配的前 3 條。
- 精準度只需「堪用」，目的是確保 Demo 不因斷線而中斷。
- relevance_score 可用簡易的匹配命中率作為替代值。

---

## 四、呼叫者與使用情境

| 呼叫者 | 情境 | 範例查詢 |
|--------|------|----------|
| A2 | 事件注入後，確認適用的 SOP 條款 | 「路面塌陷、Closed、Critical、affected_segment 為 RD_ 開頭」 |
| A2 | 確認觸發動作與處置步驟 | 「飽和度達 0.95 以上應觸發什麼」 |
| W1 | 評審問 What-if 時需引用 SOP 原文 | 「BL17 人數超過 25000 會觸發什麼條款」 |
| W1 | 評審直接問 SOP 規則內容 | 「ETE 的計算公式是什麼」 |

---

## 五、不屬於 K3 的事（明確排除）

- ❌ 判斷事件級別（那是 P4/P5 的工作）
- ❌ 計算路線或 ETE（那是 R1~R5 和 A3 的工作）
- ❌ 判斷使用者意圖是否為閒聊（那是 W1 的工作）
- ❌ 改寫或摘要 SOP 內容（K3 只回傳原文）
- ❌ 定義 SOP JSON 的 schema（由資料層負責）

---

## 六、成功標準

1. 給定任何一筆 `live_incidents.json` 中的事件描述作為查詢，K3 能回傳正確對應的 SOP 條款（例如 Road_Collapse → 第 2 條、Power_Failure → 第 5 條）。
2. 回傳的 content 與 `emergency_traffic_sop.json` 中的原文完全一致。
3. 雲端模式與本機模式的回傳格式相同（只有精準度不同），呼叫者不需要區分模式。
4. 無相關結果時不回傳錯誤的條款。

---

## 七、待整合時確認（不在本 spec 定義）

- K3 的具體 function signature / API endpoint 格式（留待與 A2、W1 整合時定義）
- SOP 索引文件的衍生格式（留待實作時決定，純文字或 Markdown）
- relevance_score 的閾值設定（留待測試時調參）
