# W2 — 對話狀態管理 | Tasks

> 前置文件：`specs/W2-session-manager/requirements.md`、`specs/W2-session-manager/design.md`
> 預估總工時：1~1.5 小時（W2 很輕量）

> **[2026-07-28 總架構師補註]** design.md 已移除 `_pending_message` 暫存機制，改成 `record_response()` 直接收 `user_message` 參數。本文件下方寫到 `Session` 含 `_pending_message` 欄位、或「暫存 `_pending_message`」的步驟，一律省略，不用實作。session_id 也不再靠 WebSocket connection 推導，改由前端產生後隨每次 `POST /api/what-if` 請求帶上（design.md 第五節）。

---

## Task 1：定義資料結構

**做什麼：** 建立 `src/session/models.py`，定義 `Turn`、`Session`、`W1Context` 三個 dataclass。

**具體步驟：**
1. 建立 `src/session/__init__.py`、`models.py`
2. 定義 `Turn`（user_message, ai_response, timestamp, triggered_sops）
3. 定義 `Session`（session_id, history, assumptions, created_at, _pending_message）
4. 定義 `W1Context`（session_id, new_message, history, accumulated_assumptions）

**完成標準：** 能 import 這三個 class，建立實例不報錯。

---

## Task 2：實作 session_manager 三個核心 function

**做什麼：** 建立 `src/session/session_manager.py`，實作 `handle_message`、`record_response`、`clear_session`。

**具體步驟：**
1. 建立全域 `SESSION_STORE: dict[str, Session] = {}`
2. 實作 `handle_message(session_id, user_message) -> W1Context`：
   - 若 session 不存在則建立
   - 暫存 `_pending_message`
   - 取最近 10 輪 history
   - 回傳 `W1Context`
3. 實作 `record_response(session_id, ai_response, triggered_sops, new_assumptions)`：
   - 建立 `Turn` 加入 history
   - 更新 assumptions（如果有）
   - 裁切超過 10 輪的部分
4. 實作 `clear_session(session_id)`：
   - 從 `SESSION_STORE` 刪除該 session

**完成標準：**
- 呼叫 `handle_message("test", "你好")` → 回傳 W1Context，history 為空
- 呼叫 `record_response("test", "歡迎")` → 再呼叫 `handle_message("test", "第二句")` → history 有 1 輪
- 呼叫 `clear_session("test")` → 再 `handle_message("test", "新對話")` → history 為空

---

## Task 3：實作假設參數累積邏輯

**做什麼：** 確保 `record_response` 中的 `new_assumptions` 正確累積與覆蓋。

**具體步驟：**
1. 在 `record_response` 中加入 `session.assumptions.update(new_assumptions)` 邏輯
2. `handle_message` 回傳的 `W1Context.accumulated_assumptions` 是 copy（避免被外部修改）

**完成標準：**
- 第一輪：`record_response(new_assumptions={"BL17.User_Count": 40000})`
- 第二輪：`record_response(new_assumptions={"RD_TPE_002.status": "Closed"})`
- 第三輪的 `W1Context.accumulated_assumptions` 包含兩個 key
- 覆蓋測試：再 `record_response(new_assumptions={"BL17.User_Count": 50000})` → 值變成 50000

---

## Task 4：實作歷史裁切（10 輪上限）

**做什麼：** 確保 history 超過 10 輪時自動丟棄最早的。

**具體步驟：**
1. 在 `record_response` 尾端加裁切邏輯
2. `handle_message` 取 history 時用 `[-MAX_HISTORY:]`

**完成標準：** 模擬連續 12 輪對話，`W1Context.history` 只保留最近 10 輪，第 1、2 輪被丟棄。

---

## Task 5：整合到 FastAPI WebSocket handler

**做什麼：** 在 FastAPI 的 WebSocket endpoint 中串接 W2。

**具體步驟：**
1. 在 WebSocket `on_connect` 時不需要特別動作（session 在第一次 `handle_message` 時建立）
2. 收到 `{"type": "chat_message", "content": "..."}` → 呼叫 `handle_message`
3. 收到 `{"type": "clear_session"}` → 呼叫 `clear_session`
4. WebSocket 斷線時（`WebSocketDisconnect`）→ 呼叫 `clear_session`
5. Session ID 用 `str(uuid4())` 在連線時生成

**完成標準：**
- 開一個 WebSocket 連線，送 chat_message → 不報錯
- 送 clear_session → 不報錯
- 關閉連線後 session 被清除（可用 print 確認）

---

## Task 6：簡易整合測試

**做什麼：** 寫一個測試 script 模擬完整多輪對話流程。

**測試案例：**

```
1. handle_message("s1", "如果 BL17 到 40000？")
   → W1Context: history=[], assumptions={}

2. record_response("s1", "依 SOP 第 3 條...", 
                   triggered_sops=[3], 
                   new_assumptions={"BL17.User_Count": 40000})

3. handle_message("s1", "那如果同時光復南路也塌了？")
   → W1Context: history=[Turn(...)], assumptions={"BL17.User_Count": 40000}

4. record_response("s1", "依 SOP 第 2 條...",
                   triggered_sops=[2],
                   new_assumptions={"RD_TPE_002.status": "Closed"})

5. handle_message("s1", "ETE 會變多久？")
   → W1Context: history=[Turn, Turn], 
     assumptions={"BL17.User_Count": 40000, "RD_TPE_002.status": "Closed"}

6. clear_session("s1")

7. handle_message("s1", "你好")
   → W1Context: history=[], assumptions={}  ← 全部清空
```

**完成標準：** 上述 7 步全部通過。

---

## 執行順序

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 6（單元測試）→ Task 5（整合到 FastAPI）
```

Task 1~4 不依賴任何外部服務，可立即開始。Task 5 需要 FastAPI server 已建好基本骨架。
