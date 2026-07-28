# W1 — What-if 問答 Agent | Tasks

> 前置文件：`specs/W1-whatif-agent/requirements.md`、`specs/W1-whatif-agent/design.md`
> 預估總工時：4~5 小時
> 前置條件：K3（Task 1~3）完成、W2 完成、Strands SDK 已安裝、Bedrock 模型已開通

> **[2026-07-28 總架構師補註]** 本文件寫在 design.md 修正之前，兩處要按修正版理解，不要照字面實作：
> - **Task 3**：`simulate_scenario` 不要 `from src.orchestrator import simulate`（那個函式不存在，而且會形成 Orchestrator→W1→Orchestrator 循環依賴）。改成直接呼叫 `routing.py`／`rules.py`／`reporting.py` 等決定性模組（確切函式簽章待與模組1/2/4對齊，design.md 已標記 TODO）。完成標準不變：`simulate_scenario` 在對應模組沒做好之前一樣回傳 `{"status": "unavailable", ...}`。
> - **Task 7**：不是「FastAPI 的 WebSocket handler 收到 `chat_message` 後呼叫 `process_whatif`」。正確流程是 `POST /api/what-if` 收到請求 → `orchestrator.handle_user_query()` 判斷是 What-if 問題 → 呼叫 `process_whatif_request()`（design.md 第十節）→ 同步回傳完整結果；WebSocket 只推播 loading 進度（`chat.loading_step.v1` 等 Envelope 格式，不是 `{"type": "chat_response", "data": ...}` 這種裸格式）。`input_lock` 前端已經本地處理（見 F6 design.md），不需要後端特別推播才能鎖定輸入框，那條可以省略。
> - Task 8「Loading 步驟推播」的方案 A/B 選擇不受影響，一樣適用；只是推播的訊息格式要套 Message Envelope。

---

## Task 1：定義回覆資料結構

**做什麼：** 建立 `src/agent/response_formatter.py`，定義 `W1Response` dataclass。

**具體步驟：**
1. 建立 `src/agent/__init__.py`、`response_formatter.py`
2. 定義 `W1Response` dataclass，包含所有欄位：
   - `intent_type`, `summary`, `triggered_sops`, `judgment_basis`, `expected_actions`
   - `route_impact`, `ete`, `current_data`, `suggested_questions`
   - `source_mode`, `tools_called`
3. 寫一個 `to_dict()` 方法（方便轉成 JSON 送前端）

**完成標準：** 能建立 W1Response 實例，呼叫 `to_dict()` 產出合法 JSON。

---

## Task 2：撰寫 System Prompt

**做什麼：** 建立 `src/agent/system_prompt.py`，把 system prompt 定義為常數。

**具體步驟：**
1. 把 design 文件中的 `SYSTEM_PROMPT` 搬過來
2. 根據實際測試結果微調用詞（這步是迭代的，先搬過來就好）
3. 定義 `DEFAULT_QUESTIONS` 作為延伸問題的 fallback

**完成標準：** `from src.agent.system_prompt import SYSTEM_PROMPT` 不報錯。

---

## Task 3：定義 Tool functions

**做什麼：** 建立 `src/agent/tools.py`，定義 `query_sop` 和 `simulate_scenario` 兩個 `@tool`。

**具體步驟：**
1. 實作 `@tool query_sop(question: str) -> dict`：呼叫 K3 的 `sop_retriever.query_sop()`
2. 實作 `@tool simulate_scenario(assumptions: dict, question: str) -> dict`：
   - 嘗試呼叫 A2（`from src.orchestrator import simulate`）
   - 如果 import 失敗或呼叫失敗 → 回傳 `{"status": "unavailable", "fallback": True}`
3. 兩個 tool 都寫好 docstring（Strands Agent 用 docstring 判斷何時呼叫）

**完成標準：**
- `query_sop("路面塌陷")` 回傳包含 section_number=2 的結果
- `simulate_scenario({"BL17.User_Count": 40000}, "如果人數到40000")` 回傳 `{"status": "unavailable", ...}`（因為 A2 還沒做）

---

## Task 4：建立 Agent 實例

**做什麼：** 建立 `src/agent/whatif_agent.py`，實作 `create_whatif_agent()` 和全域 Agent 實例。

**具體步驟：**
1. import system_prompt 和 tools
2. 用 `Agent(model=..., tools=[...], system_prompt=...)` 建立 Agent
3. model ID 從環境變數 `BEDROCK_MODEL_ID` 讀取
4. 建立全域 `WHATIF_AGENT` 實例

**完成標準：** 直接在 terminal 跑一個簡單測試：

```python
from src.agent.whatif_agent import WHATIF_AGENT
print(WHATIF_AGENT("你好"))
```

能收到一段 LLM 回覆（閒聊模式，不呼叫 tool）。

> ⚠️ 此 Task 需要 Bedrock 模型已開通。如果還沒開通，先跳到 Task 5 寫格式化邏輯。

---

## Task 5：實作回覆格式化器

**做什麼：** 在 `response_formatter.py` 中實作 `format_response()` 函式。

**具體步驟：**
1. 從 Agent 回覆中提取 tool call 結果（透過 Strands 的 trace/history 機制）
2. 根據呼叫了哪些 tool 判定 `intent_type`
3. 從 `query_sop` 結果填入 `triggered_sops`
4. 從 `simulate_scenario` 結果填入 `ete`, `route_impact`, `expected_actions` 等
5. 從 Agent 最終文字回覆中提取 `summary`（取第一段或第一句）
6. 從 Agent 回覆中解析延伸問題（搜尋列表格式的問題句）
7. 若解析不到延伸問題，使用 `DEFAULT_QUESTIONS`

**完成標準：** 給一個模擬的 Agent 回覆（硬寫的），能正確轉成 `W1Response`。

---

## Task 6：實作主流程 process_whatif()

**做什麼：** 在 `whatif_agent.py` 中實作 `process_whatif(context: W1Context) -> W1Response`。

**具體步驟：**
1. 實作 `_build_prompt(context)` — 把 history + assumptions + new_message 組成 prompt
2. 呼叫 `WHATIF_AGENT(prompt)` 取得 raw response
3. 呼叫 `format_response(raw_response, context)` 取得 W1Response
4. 加上 try/except：LLM 呼叫失敗時回傳錯誤用的 W1Response

**完成標準：**

```python
from src.session.models import W1Context
from src.agent.whatif_agent import process_whatif

context = W1Context(
    session_id="test",
    new_message="如果 BL17 人數到 40000 會觸發什麼？",
    history=[],
    accumulated_assumptions={}
)
response = process_whatif(context)
print(response.intent_type)        # "whatif_simulation" 或 "sop_query"
print(response.triggered_sops)     # 至少包含 section_number=3
print(response.suggested_questions) # 有 3 個問題
```

---

## Task 7：整合到 WebSocket handler

**做什麼：** 在 FastAPI 的 WebSocket handler 中串接 W2 → W1 完整流程。

**具體步驟：**
1. 收到 `chat_message` → 呼叫 `handle_message(session_id, content)` 取得 W1Context
2. 呼叫 `process_whatif(context)` 取得 W1Response
3. 用 `websocket.send_json({"type": "chat_response", "data": response.to_dict()})` 推送
4. 呼叫 `record_response(session_id, response.summary, ...)` 讓 W2 記錄
5. 加上輸入鎖定提示：處理開始推 `{"type": "input_lock", "locked": true}`，完成推 `false`

**完成標準：** 用 WebSocket 測試工具（或簡單的 HTML 頁面）送訊息，能收到完整的 chat_response JSON。

---

## Task 8：實作 Loading 步驟推播

**做什麼：** 建立 `src/agent/loading.py`，在處理過程中逐步推送進度。

**具體步驟：**
1. 定義 `LOADING_STEPS` 列表
2. 在 `process_whatif` 中的關鍵點插入推播：
   - 開始 → step 1 active
   - query_sop tool 呼叫前 → step 2 active
   - simulate_scenario tool 呼叫前 → step 3 active
   - 格式化完成 → 全部 done
3. 由於 Strands Agent 可能不支援中途 callback，採用替代方案：
   - **方案 A**：在 tool function 內部主動推播（需傳入 websocket 參考）
   - **方案 B**：退化為兩段式（開始 loading → 完成），省略中間步驟
4. 先實作方案 B（保證能用），有時間再改方案 A

**完成標準：** 前端收到 `loading_start` → 等待 → 收到 `chat_response`，中間不斷線。

---

## Task 9：System Prompt 調優

**做什麼：** 用實際問題測試 Agent，調整 system prompt 讓回覆品質更好。

**測試案例：**

| # | 輸入 | 期望行為 |
|---|------|---------|
| 1 | 「你好」 | 不 call tool，直接回覆引導語 + 3 個延伸問題 |
| 2 | 「ETE 怎麼算？」 | call query_sop → 引用第 7 條原文回答 |
| 3 | 「如果 BL17 人數到 40000」 | call query_sop + simulate_scenario → 完整 Decision Card 內容 |
| 4 | 「那如果同時光復南路也塌了？」（接續第 3 題） | 帶入累積假設，call 兩個 tool |
| 5 | 「台灣總統是誰？」 | 不 call tool，禮貌拒絕 + 引導 |
| 6 | 「如果下大雨怎麼辦？」 | call query_sop → 回傳空 → 標示 SOP 未涵蓋 + 推測 |

**調優方向：**
- 如果 Agent 不必要地 call tool（例如閒聊也呼叫 query_sop）→ 調整 tool 的 docstring
- 如果回覆太冗長 → 在 prompt 加「簡潔回答」指示
- 如果延伸問題品質差 → 在 prompt 加更具體的延伸問題格式要求

**完成標準：** 6 個測試案例的行為都符合預期。

---

## Task 10：端到端整合測試

**做什麼：** 完整跑一輪 Demo 情境，確保 F6 → API → W2 → W1 → K3 全串通。

**測試情境：**

```
1. 前端送「目前系統是什麼應變等級？」
   → 收到包含 SOP §1 的回覆 + 延伸問題

2. 點擊延伸問題「如果 BL17 人數達 40000？」
   → 收到包含 SOP §3 的 Decision Card + ETE（若 A2 可用）

3. 手動輸入「那如果同時光復南路也塌了？」
   → 收到累積兩個假設的結果 + SOP §2 + §3

4. 點「清除對話」
   → 畫面清空，下一個問題不帶歷史

5. 輸入「你好」
   → 收到閒聊回覆 + 引導
```

**完成標準：** 5 步全部順暢完成，無報錯。

---

## 執行順序建議

```
不需要 Bedrock（可立即開始）：
  Task 1 → Task 2 → Task 3（query_sop tool 需 K3 Task 1~3 完成）

需要 Bedrock 模型開通：
  Task 4 → Task 6 → Task 5

需要 FastAPI + W2 整合：
  Task 7 → Task 8

最後打磨：
  Task 9 → Task 10
```

**關鍵路徑：** Task 1~3 可以先全部做好（不需要 AWS），Task 4 開始才需要 Bedrock 通。
