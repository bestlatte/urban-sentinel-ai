---
inclusion: always
---

# 測試策略與 AI 協作規則（Testing & AI Collaboration Rules）

本檔是本專案**測試要求與 Kiro 協作方式的唯一權威**。與 `00-tech-stack.md`（技術棧）、`01-module-boundaries.md`（模組邊界）、`02-data-contract.md`（資料契約）同為 always-load，具同等拘束力。

依據原則：本專案核心設計是「事實計算不依賴 LLM」（見 `01-module-boundaries.md` 三層原則）。這個設計的存在意義之一，就是讓大部分邏輯可以用**精確斷言**驗證，不必靠人工 review 猜對錯。測試不是額外負擔，是這個架構選擇的直接後果。

---

## 1. 測試是交付的一部分，不是事後補充

每個 `src/*.py` 完成時必須連同 `tests/test_*.py` 一起產出。**只有實作、沒有對應測試檔，視為該任務未完成。**

測試內容不是另外發明的，直接來源就是各 spec 文件的「驗收測試 / Acceptance Criteria」章節——那些表格本來就是為了逐條變成 `assert` 而寫的，寫 spec 時就已經用「可測試」的角度設計過，不是給人看的敘述文字。Kiro 讀 spec 時，應把該章節逐行轉成 `tests/test_<module>.py` 裡的一個測試函式。

若某條驗收測試在實作後無法通過：視為實作有誤，**不得跳過、不得註解掉斷言、不得放寬允許誤差**去讓測試通過。應回頭檢查實作邏輯或（更少見）回頭確認 spec 本身的黃金值是否有誤（黃金值皆已對照真實資料人工複算過，見各 spec 第六節）。

---

## 2. 依模組性質分兩種斷言方式

### 2.1 決定性模組 → 精確值斷言（golden value）

適用：`loaders.py`、`rules.py`、`routing.py`、`reporting.py`（A3 ETE / C1-C4 的事實計算部分）、`models.py`、`session/session_manager.py`（W2，[2026-07-28新增] 純 Python 對話狀態管理，零 LLM）、`bedrock_service/local_fallback.py`／`bedrock_service/sop_data.py`（[2026-07-28新增] K3 本機關鍵字比對與 SOP 預載，零 LLM，跟同目錄下 `bedrock_kb.py` 的雲端呼叫部分性質不同，不要因為都在 `bedrock_service/` 底下就整包歸進 2.2）。

這些是純 Python、零 LLM 介入，同樣輸入必須永遠得到同樣輸出。一律用**精確值**斷言，不接受「大概對」「在合理範圍內」的近似斷言：

- ETE 必須等於 90 / 70 / 41 分鐘（ACC_001 / EVT_002 / EVT_003），不是「約 90 分鐘」
- SOP-6 觸發必須是 `BS_TPE_101=0.40`、`BS_XY_ATT=0.30`；`BS_TPE_DOME`（真實漫遊率約 0.05~0.06）必須斷言為**不觸發**
- 真實 CSV 的 `Roaming_User_Pct` 字串解析（`"40%"` → `0.40`）要有專門測試，不能只測已經轉換好的數字
- SOP-1 的 A/B 分級適用全 15 路段、僅「城市應變觸發」限定 RD_TPE_001/002 兩段——這兩件事要分開斷言（此前這裡曾經寫錯成分級本身也被限制在 2 段，已修正，見 `m1-data-ingestion/requirements.md` 測試 #6b，之後任何改動都要保留這條回歸測試）

### 2.2 LLM 相關模組 → 結構性事實不變斷言

適用：`agent.py`、`bedrock_service/bedrock_kb.py`（[2026-07-28更正] 僅雲端呼叫部分，不含已歸入 2.1 的 `local_fallback.py`／`sop_data.py`）、`orchestrator.py` 的 C1-C4／LLM_A2（解釋敘述）部分。

LLM 輸出的**文字內容**本身不斷言（每次用詞可能不同，這是預期行為，不是 bug）。改斷言 LLM 輸出裡引用的**事實欄位**必須與上游決定性計算結果逐字相同，一個字元都不能被 LLM 改寫：

- `event_id` / `location` / `severity` / `route`（主/次路線編號）/ `ete_minutes` / 引用的 SOP 條款編號
- 若斷言發現這些欄位被 LLM 改動（例如 ETE 從 90 被 LLM 敘述成「約 1 小時」而非原樣帶出 90 分鐘數字），視為 prompt 設計錯誤，須修正 prompt 契約，不是接受這個輸出

此外每個 LLM 模組必須有一條測試驗證 `USE_BEDROCK=false` 保底模式：走本機關鍵字比對 / 固定模板，仍能跑完「感知 → 決策 → 通報」全流程（見 `00-tech-stack.md` 第 6 節），不得因為 Bedrock 不可用而整條流程失敗或吞掉錯誤。

### 2.3 契約層

`models.py` / `contracts/module_exchange_contract.json`：驗證 Pydantic model 序列化後的欄位名稱、型別、必填/選填，逐一對照 `02-data-contract.md` 的欄位表，不得憑印象假設欄位存在。

---

## 3. Docstring 規範：只寫「為什麼」，不寫「做什麼」

函式名與型別簽章已經說明 what；docstring 只補「為什麼這樣算」「這裡為什麼要這樣處理」——凡是刪掉 docstring 也不會讓讀者看不懂函式在幹嘛的，就不該寫。

- 邏輯來自某條 SOP 或某個 Requirement 時，docstring 第一行寫明依據，例如：
  ```python
  def check_roaming_trigger(roaming_ratio: float) -> bool:
      """SOP-6：漫遊比率 >= 0.30 觸發多語簡訊（C4）。閾值來自主辦方 SOP 原文，非團隊自訂。"""
  ```
- 不直覺的設計決策要寫清楚原因：**寫決策 + 原因，不是重述程式碼在做什麼**。
- 不寫「使用於 XX 流程」「由 XX 呼叫」這類會隨程式演進而過時的呼叫端說明——那是 code review / spec 該講的事，不該寫死在 docstring 裡。

---

## 4. Kiro／AI 協作原則（給生成程式碼時遵守）

1. **小顆粒度餵 spec，不要整包丟。** 依 `INDEX.md` 的建置順序，一次只讀該階段需要的文件。長 context 下 AI 生成品質會隨位置後移而衰減，分階段餵是刻意的效能與品質設計，不是圖方便。
2. **先讀 spec 全文再動手，不要看到一半就開始生成。** 尤其驗收測試章節必須完整讀完，因為測試案例之間可能互相補充邊界情況（例如 D1-data-ingestion 的 #6 與 #6b 兩條分開驗證「一般分級」與「城市應變觸發限定」，只讀 #6 會漏掉限定範圍的部分）。
3. **驗收測試沒過 = 沒做完，自己迭代到過。** 不要交出「大部分測試過、剩幾條先跳過」的結果。
4. **不確定 spec 是否有衝突或缺漏時，明確標記出來，不要自己猜一個答案填上去。** 本專案的 AI 侷限對策就是「人做架構判斷、AI 做規格內的實作」——Kiro 遇到 spec 本身矛盾或欄位缺失，正確行為是停下來報告，不是選一個合理版本繼續生成。
5. **事實與表達要在程式碼結構上物理分開，不要靠命名或註解區分。** 決定性計算函式與 LLM 呼叫函式必須是不同函式、不同檔案職責（見 `01-module-boundaries.md` 三層原則），不能把「算 ETE」跟「用 LLM 潤飾 ETE 敘述」寫在同一個函式裡，否則測試無法對兩者分開斷言。
6. **禁用清單是為了省資源存在的，不是形式規定。** `00-tech-stack.md` 明列的禁用技術（React、Leaflet/Mapbox、Kafka/SQS 等）先幫 AI 排除選項，比事後 code review 抓錯更省 token——生成時不要因為「更常見」或「更熟悉」而引入清單外的技術，即使功能上看起來合理。
