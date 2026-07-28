# W2 — 對話狀態管理 | Design

> 前置文件：`specs/W2-session-manager/requirements.md`
> 本文件定義 W2 的技術實作方式。

> **[2026-07-28 總架構師補註]** 兩處修正：
> 1. **Session ID 不能再靠 WebSocket connection 推導**——`W1-whatif-agent/design.md` 已修正為聊天訊息走 `POST /api/what-if`（REST，無狀態，跟 F6 design.md 的修正一致），不是透過 WebSocket 收送。REST 請求沒有「同一條連線」可以取 connection id。改為：session_id 由前端（F6）在頁面載入時產生一次（`crypto.randomUUID()`），存在 `ChatState.sessionId`，之後每次 `POST /api/what-if` 的 request body 都帶著同一個 session_id；WebSocket 若也要跟同一個對話關聯（例如冗餘推播比對 correlation_id），一樣傳同一個 session_id，不是反過來由連線推導 session_id。第五節已重寫。
> 2. **`_pending_message` 暫存機制改成直接傳參數**——原本靠 `session._pending_message` 這個可變屬性在 `handle_message()` 和 `record_response()` 兩次呼叫間傳遞使用者訊息，這種跨呼叫的隱性狀態容易在時序調整時out-of-sync（例如未來要支援同一 session 並發請求時會直接錯亂）。改為 `record_response()` 直接收 `user_message` 參數，呼叫端（`process_whatif_request()`，見 `W1-whatif-agent/design.md` 第十節）本來就同時握有這個值，不需要暫存。第三、四節已同步修正。

---

## 一、架構總覽

```
F6 (前端)
   │ WebSocket 訊息
   ▼
API Gateway (FastAPI)
   │ 識別 session_id（從 WebSocket connection）
   ▼
┌─────────────────────────────────────┐
│            W2 模組                   │
│                                     │
│  SessionStore（記憶體 dict）          │
│    key = session_id                 │
│    value = Session 物件              │
│      ├─ history: list[Turn]         │
│      ├─ assumptions: dict           │
│      └─ created_at: datetime        │
│                                     │
│  組合上下文 → 交給 W1                 │
└─────────────────────────────────────┘
   │
   ▼
W1 (What-if Agent)
```

W2 很輕量：一個 Python dict 存所有 session，每個 session 裡面是對話歷史 + 假設參數。

---

## 二、資料結構

```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class Turn:
    """一輪對話 = 使用者問一次 + AI 答一次"""
    user_message: str
    ai_response: str          # W1 回覆的自然語言摘要
    timestamp: datetime
    triggered_sops: list[int] = field(default_factory=list)  # 這輪觸發的 SOP 編號（方便上下文）

@dataclass
class Session:
    """一個對話 session 的完整狀態"""
    session_id: str
    history: list[Turn] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)   # 累積的假設參數
    created_at: datetime = field(default_factory=datetime.now)

# 全域 session 存放
SESSION_STORE: dict[str, Session] = {}
```

### `assumptions` 的結構

```python
# 範例：使用者說了「假設 BL17 人數到 40000」再說「假設光復南路也塌了」
assumptions = {
    "BS_MRT_BL17.User_Count": 40000,
    "RD_TPE_002.status": "Closed"
}
```

- key：`{entity}.{field}` 格式（由 W1 解析後回傳）
- value：假設的值
- 同一個 key 被重新假設時，覆蓋舊值

---

## 三、對外介面

### 3.1 處理新訊息（主要入口）

```python
def handle_message(session_id: str, user_message: str) -> W1Context:
    """
    收到使用者新訊息時呼叫。
    1. 取得或建立 session
    2. 組合上下文
    3. 回傳給 W1 使用的 context 物件
    """
```

### 3.2 記錄 AI 回覆（W1 回答後回呼）

```python
def record_response(session_id: str, user_message: str, ai_response: str,
                    triggered_sops: list[int] = None,
                    new_assumptions: dict = None):
    """
    W1 回覆完成後呼叫。呼叫端（process_whatif_request()）本來就同時握有
    user_message 與 ai_response，直接傳參數，不靠 session 上的暫存屬性。
    1. 把這輪對話存入 history
    2. 若有新假設參數，更新 assumptions
    """
```

### 3.3 清除 session

```python
def clear_session(session_id: str):
    """使用者點擊清除按鈕，或 WebSocket 斷線時呼叫。"""
```

### 3.4 交給 W1 的上下文結構

```python
@dataclass
class W1Context:
    """W2 組合好、交給 W1 的完整上下文"""
    session_id: str
    new_message: str                    # 使用者本次輸入
    history: list[Turn]                 # 最近 N 輪（N ≤ 10）
    accumulated_assumptions: dict       # 目前所有假設參數
```

---

## 四、內部邏輯

### 4.1 handle_message 流程

```python
MAX_HISTORY = 10

def handle_message(session_id: str, user_message: str) -> W1Context:
    # 1. 取得或建立 session
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = Session(session_id=session_id)
    
    session = SESSION_STORE[session_id]
    
    # 2. 組合上下文（只取最近 10 輪）
    recent_history = session.history[-MAX_HISTORY:]
    
    return W1Context(
        session_id=session_id,
        new_message=user_message,
        history=recent_history,
        accumulated_assumptions=session.assumptions.copy()
    )
```

### 4.2 record_response 流程

```python
def record_response(session_id: str, user_message: str, ai_response: str,
                    triggered_sops: list[int] = None,
                    new_assumptions: dict = None):
    session = SESSION_STORE.get(session_id)
    if not session:
        return  # session 已被清除，忽略
    
    # 1. 把這輪加入 history（user_message 由呼叫端直接傳入，不靠暫存屬性）
    turn = Turn(
        user_message=user_message,
        ai_response=ai_response,
        timestamp=datetime.now(),
        triggered_sops=triggered_sops or []
    )
    session.history.append(turn)
    
    # 2. 更新假設參數
    if new_assumptions:
        session.assumptions.update(new_assumptions)
    
    # 3. 超過上限就裁切
    if len(session.history) > MAX_HISTORY:
        session.history = session.history[-MAX_HISTORY:]
```

### 4.3 clear_session 流程

```python
def clear_session(session_id: str):
    if session_id in SESSION_STORE:
        del SESSION_STORE[session_id]
```

---

## 五、Session ID 的來源

- session_id 由前端（F6）在頁面載入時產生一次（`crypto.randomUUID()`，存在 `ChatState.sessionId`，見 `F6-chat-ui/design.md`），之後每次 `POST /api/what-if` 的 request body 都帶著同一個 session_id。
- 不依賴 WebSocket connection——聊天訊息走 REST（`00-tech-stack.md` §4「狀態改變操作走 REST」），REST 請求是無狀態的，沒有「同一條連線」可以推導 session_id。
- 若前端頁面重整 → `ChatState.sessionId` 重新產生 → 新 session（等同清除）。
- WebSocket 的 `chat.clear_session.v1`（例外維持走 WS，見 F6 design.md）payload 裡一樣帶 session_id，不靠 connection 識別。

```python
# main.py：POST /api/what-if
@app.post("/api/what-if")
async def what_if(body: WhatIfRequest):  # body 含 session_id, content, correlation_id
    context = handle_message(body.session_id, body.content)
    response = process_whatif(context)  # W1
    record_response(
        session_id=body.session_id,
        user_message=body.content,
        ai_response=response.summary,
        triggered_sops=[s["section_number"] for s in response.triggered_sops],
        new_assumptions=_extract_new_assumptions(response),
    )
    return build_envelope("chat.response.v1", asdict(response), correlation_id=body.correlation_id)

# WebSocket handler：只處理 clear_session（例外維持走 WS），其餘訊息不再經這裡
async def handle_ws_message(websocket, envelope: dict):
    if envelope["message_type"] == "chat.clear_session.v1":
        session_id = envelope["payload"]["session_id"]
        clear_session(session_id)
        await websocket.send_json(build_envelope("chat.session_cleared.v1", {}))
```

---

## 六、錯誤處理

| 情境 | 處理方式 |
|------|---------|
| session_id 不存在（已被清除但又收到 record_response） | 靜默忽略，不報錯 |
| history 超過 MAX_HISTORY | 自動裁切保留最近 10 輪 |
| assumptions 中同一個 key 被重複設定 | 後來的覆蓋先前的（dict.update） |
| Server 重啟 | 所有 session 遺失（Demo 可接受） |

---

## 七、檔案結構（預期）

```
src/
└── session/
    ├── __init__.py
    ├── models.py            # Turn, Session, W1Context 資料結構定義
    └── session_manager.py   # handle_message, record_response, clear_session
```
