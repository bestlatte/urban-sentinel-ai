# F6 — 對話視窗前端 | Design

> 前置文件：`specs/F6-chat-ui/requirements.md`
> 技術：HTML / CSS / 原生 JS（不使用 React）
> 參考：`module3-ui-prototype.html`（已有的視覺原型）

> **[2026-07-28 總架構師補註]** 本文件下方多處寫 `static/css/`、`static/js/`，但 `00-tech-stack.md` §3 固定目錄結構定義的是 `frontend/{css/, js/, assets/, vendor/}`，`main.py` 掛載靜態檔也是掛 `frontend/`，沒有 `static/` 這個路徑。實作時全部改成 `frontend/css/`、`frontend/js/`，HTML 裡的 `<link>`/`<script>` 路徑同步改成 `/frontend/css/...`、`/frontend/js/...`（或依 `main.py` 實際掛載的前綴）。本文件下方的 `static/` 字樣視為筆誤，不是新的目錄約定。
>
> 另外，第三節 WebSocket 訊息格式（`{"type": "chat_response", "data": {...}}`）沒有使用 `02-data-contract.md` §7 規定的共用 Message Envelope（`schema_version`／`message_id`／`correlation_id`／`message_type`／`source_module`／`target_module`／`generated_at`／`status`／`provenance`／`warnings`／`errors`／`payload`）。因為 `/ws` 是全專案唯一一條 WebSocket，F1-F7 共用同一個連線，前端要用 `message_type` 做分派（`00-tech-stack.md` §4）；F6 若自訂一套不同欄位名的協定，會跟其他模組推播的訊息格式不一致，前端 `ws.js` 沒辦法用同一套邏輯分派。第三節與第五節已一併修正為 Envelope 格式，`type`/`data` 全部改成 `message_type`/`payload`。
>
> **[2026-07-28 二次補註] 使用者訊息改走 REST，不再送 WebSocket**——跟 `W1-whatif-agent/design.md` 一起發現的問題：`00-tech-stack.md` §4 明訂「所有改變狀態的操作走 REST；POST 必須同步回傳完整結果，WebSocket 只是額外通知」，且 `m4-explanation-chain-and-orchestrator/SPEC-O3` 的對外入口也是 `POST /api/what-if`，不是 WebSocket。原本 F6 把「送出聊天訊息」（`chat.message.v1`）當成 WebSocket 訊息送出，等於把使用者的問題本身當成推播頻道傳輸，違反這條規則。已修正：`sendMessage()` 改成呼叫 `POST /api/what-if`，同步等待完整回覆後直接渲染，不再依賴 WebSocket 收 `chat.response.v1` 才能顯示結果；WebSocket 只保留 loading 進度與（可選的）冗餘推播。`clear_session` 維持走 WebSocket——這不是決策狀態的一部分，只是 W2 對話 session 的本地清空，不在固定 4 端點的職責範圍內，屬於刻意的例外，不是遺漏。

---

## 一、架構總覽

```
┌─────────────────────────────────────────────────────────┐
│                        頁面                              │
│                                                         │
│  ┌─────────────────────────┐  ┌──────────────────────┐ │
│  │   Dashboard 主區域       │  │   F6 Chat Panel      │ │
│  │   （其他模組負責）       │  │                      │ │
│  │                         │◄─┤  可拖拉左邊緣         │ │
│  │                         │  │                      │ │
│  │                         │  │  ┌── Status Banner ─┐│ │
│  │                         │  │  ├── Messages Area ─┤│ │
│  │                         │  │  ├── Quick Qs ──────┤│ │
│  │                         │  │  └── Input Area ────┘│ │
│  │                         │  │                      │ │
│  └─────────────────────────┘  └──────────────────────┘ │
│                                                         │
│  ┌─── 收合時只顯示 ──────────────────────────────────┐  │
│  │  [💬] 浮動按鈕（右下角）                           │  │
│  └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

F6 是一個獨立的 HTML/CSS/JS 模組，可以嵌入任何 Dashboard 頁面。它只需要一個 WebSocket URL 就能運作。

---

## 二、元件拆解

### 2.1 頂層容器與收合/展開

```html
<!-- 收合狀態：浮動按鈕 -->
<button id="chat-toggle-btn" class="chat-fab">💬</button>

<!-- 展開狀態：右側面板 -->
<div id="chat-panel" class="chat-panel collapsed">
  <div class="chat-resize-handle"></div>  <!-- 左邊緣拖拉條 -->
  <div class="chat-header">...</div>
  <div class="chat-status-banner">...</div>
  <div class="chat-messages">...</div>
  <div class="chat-quick-questions">...</div>
  <div class="chat-input-area">...</div>
</div>
```

### 2.2 狀態管理（純 JS 變數）

```javascript
const ChatState = {
  isOpen: false,           // 面板展開/收合
  isLocked: false,         // 輸入框鎖定（AI 回覆中）
  panelWidth: 420,         // 面板寬度（px）
  messages: [],            // 畫面上的訊息列表（僅供渲染，非 source of truth）
  wsConnection: null,      // WebSocket 連線物件
  hasFirstMessage: false,  // 是否已送出第一則訊息（控制快捷問題顯示）
  currentCorrelationId: null,  // 本輪對話的 correlation_id，送出訊息前產生，收到 chat.response.v1 後可清空
  sessionId: null,         // W2 session id，頁面載入時產生一次（例如 crypto.randomUUID()），REST 與 WebSocket 共用同一個值
};
```

---

## 三、WebSocket 通訊協定

所有訊息（前端送出與後端推播）一律套用 `02-data-contract.md` §7 的共用 Message Envelope；分派鍵是 `message_type`，實際內容在 `payload` 裡，不是自訂的 `type`/`data`。同一次對話輪次共用同一個 `correlation_id`（例如同一則使用者訊息觸發的 `loading_start` → `loading_step` × N → `chat_response`，四則訊息 `correlation_id` 相同）。

### 3.1 前端 → 後端（送出）

使用者的問題**不走 WebSocket**，改用 REST：

```javascript
// POST /api/what-if
// Request body：
{ "session_id": "sess_xxx", "content": "如果 BL17 人數到 40000？", "correlation_id": "corr_xxx" }

// Response body（同步回傳，套用 Message Envelope）：
{
  "schema_version": "1.0",
  "message_id": "msg_yyy",
  "correlation_id": "corr_xxx",
  "message_type": "chat.response.v1",
  "source_module": "bedrock_advisor",
  "target_module": "dashboard",
  "generated_at": "2026-07-28T22:10:12+08:00",
  "status": "ok",
  "payload": { "...W1Response 全部欄位，見第四節 renderAIResponse..." }
}
```

只有「清除對話」維持走 WebSocket——這不是決策狀態，只是 W2 對話 session 的本地清空，不佔用固定 4 端點：

```javascript
// 清除對話（WebSocket，例外保留）
{ "...envelope 欄位同上...", "message_type": "chat.clear_session.v1", "payload": { "session_id": "sess_xxx" } }
```

### 3.2 後端 → 前端（接收）

```javascript
// Loading 開始
{ "...envelope...", "message_type": "chat.loading_start.v1", "payload": {} }

// Loading 步驟更新
{ "...envelope...", "message_type": "chat.loading_step.v1",
  "payload": { "step": "檢索 SOP 條款", "status": "active" } }  // active | done

// AI 回覆（完整結果）—— 內容跟 POST /api/what-if 的 response body 是同一份（雙通道保底，
// 前端以 POST 的同步回傳為主，這裡是額外冗餘推播，兩邊 correlation_id 相同）
{
  "schema_version": "1.0",
  "message_id": "msg_yyy",
  "correlation_id": "corr_xxx",
  "message_type": "chat.response.v1",
  "source_module": "bedrock_advisor",
  "target_module": "dashboard",
  "generated_at": "2026-07-28T22:10:12+08:00",
  "status": "ok",
  "provenance": { "current_data": "provided" },
  "warnings": [],
  "errors": [],
  "payload": {
    "intent_type": "whatif_simulation",
    "summary": "依 SOP 第 3 條，BL17 超過 25000 人應觸發捷運分流...",
    "triggered_sops": [{"section_number": 3, "title": "捷運與接駁分流", "content": "..."}],
    "judgment_basis": "BS_MRT_BL17 User_Count = 40,000 > 25,000 門檻",
    "expected_actions": ["建議北捷過站不停", "通知公車處調度接駁專車", "引導群眾步行至 BL18"],
    "route_impact": {"blocked": ["光復南路"], "primary": "仁愛路四段", "secondary": "市府路"},
    "ete": {"minutes": 89, "formula": "60 + (0.99-0.5)*60", "recovery_time": "23:40"},
    "current_data": {"BL17_user_count": 31000, "BL17_growth_rate": 0.08},
    "suggested_questions": ["如果同時散場機制啟動呢？", "替代路線容量夠嗎？", "ETE 能縮短嗎？"],
    "source_mode": "full",
    "tools_called": ["query_sop", "simulate_scenario"]
  }
}

// 輸入鎖定控制
{ "...envelope...", "message_type": "chat.input_lock.v1", "payload": { "locked": true } }

// 系統狀態更新（給 Status Banner）
{ "...envelope...", "message_type": "chat.system_status.v1",
  "payload": { "level": "A", "description": "光復南路封閉", "ete_minutes": 90 } }

// Session 已清除確認
{ "...envelope...", "message_type": "chat.session_cleared.v1", "payload": {} }
```

上面 `"...envelope..."` 代表跟 `chat.message.v1` 範例同樣的完整欄位集，實作時不得省略。

---

## 四、各元件詳細設計

### 4.1 Chat Header

```html
<div class="chat-header">
  <div class="chat-header-icon">🤖</div>
  <div class="chat-header-text">
    <h3>策略諮詢顧問</h3>
    <p>Interactive Strategic Advisory</p>
  </div>
  <div class="chat-header-actions">
    <button id="clear-btn" title="清除對話">🗑️</button>
    <button id="collapse-btn" title="收合">✕</button>
  </div>
</div>
```

- 清除按鈕點擊 → 彈出 confirm → 送 `clear_session` → 清空 messages 區域
- 收合按鈕 → 面板滑出 + 顯示浮動按鈕

### 4.2 Status Banner

```html
<div class="chat-status-banner" id="status-banner">
  <span class="status-dot level-a"></span>
  <span class="status-text">A 級應變中 | 光復南路封閉 | ETE 90 min</span>
</div>
```

- 收到 `chat.system_status.v1` 訊息時更新內容和顏色
- CSS class：`.level-a`（紅）、`.level-b`（橘，對齊 `02-data-contract.md` §8）、`.level-normal`（綠）

### 4.3 Messages Area

訊息區使用 DOM 動態插入，每則訊息是一個 `div.msg`：

```javascript
function renderUserMessage(text) {
  const html = `
    <div class="msg msg-user">
      <div class="msg-avatar">你</div>
      <div class="msg-content">
        <div class="msg-bubble">${escapeHtml(text)}</div>
        <div class="timestamp">${formatTime()}</div>
      </div>
    </div>`;
  appendToMessages(html);
}

function renderAIResponse(data) {
  // 1. 摘要氣泡
  let html = `<div class="msg msg-ai"><div class="msg-avatar">AI</div><div class="msg-content">`;
  html += `<div class="msg-bubble">${escapeHtml(data.summary)}</div>`;
  
  // 2. Decision Card（只在 sop_query 或 whatif_simulation 時顯示）
  if (data.intent_type !== "chitchat") {
    html += renderDecisionCard(data);
  }
  
  // 3. 延伸問題
  html += renderSuggestedQuestions(data.suggested_questions);
  
  html += `<div class="timestamp">${formatTime()}</div></div></div>`;
  appendToMessages(html);
}
```

### 4.4 Decision Card 渲染

```javascript
function renderDecisionCard(data) {
  let card = `<div class="decision-card">`;
  
  // Header
  card += `<div class="decision-card-header">⚠️ ${
    data.intent_type === "whatif_simulation" ? "What-if 模擬結果" : "SOP 查詢結果"
  }</div>`;
  
  card += `<div class="decision-card-body">`;
  
  // 觸發條款（SOP Badges）
  if (data.triggered_sops && data.triggered_sops.length > 0) {
    card += `<div class="decision-row">
      <span class="decision-row-label">觸發條款</span>
      <span class="decision-row-value"><div class="badge-group">`;
    data.triggered_sops.forEach(sop => {
      card += `<span class="sop-badge">SOP §${sop.section_number} ${sop.title}</span>`;
    });
    card += `</div></span></div>`;
  }
  
  // 判定依據
  if (data.judgment_basis) {
    card += `<div class="decision-row">
      <span class="decision-row-label">判定依據</span>
      <span class="decision-row-value">${escapeHtml(data.judgment_basis)}</span>
    </div>`;
  }
  
  // 預期動作
  if (data.expected_actions && data.expected_actions.length > 0) {
    card += `<div class="decision-row">
      <span class="decision-row-label">預期動作</span>
      <span class="decision-row-value">`;
    data.expected_actions.forEach((action, i) => {
      card += `${String.fromCharCode(9312 + i)} ${escapeHtml(action)}<br>`;
    });
    card += `</span></div>`;
  }
  
  // 路網影響（Route Tags）
  if (data.route_impact) {
    card += `<div class="decision-row">
      <span class="decision-row-label">路網影響</span>
      <span class="decision-row-value"><div class="badge-group">`;
    if (data.route_impact.blocked) {
      data.route_impact.blocked.forEach(r => {
        card += `<span class="route-tag blocked">${escapeHtml(r)} (封閉)</span>`;
      });
    }
    if (data.route_impact.primary) {
      card += `<span class="route-tag primary-route">→ ${escapeHtml(data.route_impact.primary)}</span>`;
    }
    if (data.route_impact.secondary) {
      card += `<span class="route-tag">${escapeHtml(data.route_impact.secondary)}</span>`;
    }
    card += `</div></span></div>`;
  }
  
  card += `</div>`; // end body
  
  // Footer（ETE + Explain 按鈕）
  card += `<div class="decision-card-footer">`;
  if (data.ete) {
    card += `<div class="ete-badge">⏱ ETE <span class="ete-value">${data.ete.minutes} min</span></div>`;
  }
  card += `<button class="btn-explain" onclick="toggleExplain(this)">🔍 查看推理過程</button>`;
  card += `</div>`;
  
  // Explain Panel（預設隱藏）
  if (data.triggered_sops && data.triggered_sops.length > 0) {
    card += `<div class="explain-panel" style="display:none;">`;
    card += `<div class="explain-panel-title">🧠 SOP 條款原文</div>`;
    data.triggered_sops.forEach(sop => {
      card += `<strong>第 ${sop.section_number} 條：${escapeHtml(sop.title)}</strong><br>`;
      card += `${escapeHtml(sop.content).replace(/\n/g, '<br>')}<br><br>`;
    });
    if (data.ete && data.ete.formula) {
      card += `<strong>ETE 計算：</strong>${escapeHtml(data.ete.formula)}<br>`;
    }
    card += `</div>`;
  }
  
  card += `</div>`; // end decision-card
  return card;
}
```

### 4.5 延伸問題按鈕

```javascript
function renderSuggestedQuestions(questions) {
  if (!questions || questions.length === 0) return "";
  let html = `<div class="suggested-questions">`;
  questions.forEach(q => {
    html += `<button class="quick-q" onclick="sendQuickQuestion(this)">${escapeHtml(q)}</button>`;
  });
  html += `</div>`;
  return html;
}

function sendQuickQuestion(btn) {
  const text = btn.textContent;
  sendMessage(text);
}
```

### 4.6 Loading 狀態

```javascript
function showLoading() {
  const html = `
    <div class="msg msg-ai" id="loading-msg">
      <div class="msg-avatar">AI</div>
      <div class="msg-content">
        <div class="loading-indicator">
          <div class="loading-dots"><span></span><span></span><span></span></div>
          <span>正在推理中...</span>
        </div>
        <div class="loading-steps" id="loading-steps"></div>
      </div>
    </div>`;
  appendToMessages(html);
}

function updateLoadingStep(step, status) {
  const stepsEl = document.getElementById("loading-steps");
  // 更新或新增步驟顯示
  // status: "active" → 藍色動畫, "done" → 綠色勾勾
}

function hideLoading() {
  const el = document.getElementById("loading-msg");
  if (el) el.remove();
}
```

### 4.7 輸入區

```javascript
async function sendMessage(text) {
  if (!text) text = document.getElementById("chat-input").value.trim();
  if (!text || ChatState.isLocked) return;
  
  // 1. 顯示使用者訊息
  renderUserMessage(text);
  document.getElementById("chat-input").value = "";
  
  // 2. 隱藏預設快捷問題（第一則訊息後）
  ChatState.hasFirstMessage = true;
  hideDefaultQuickQuestions();
  
  // 3. 顯示 loading + 鎖定輸入（本地立即鎖定，不等後端的 chat.input_lock.v1 推播）
  showLoading();
  setInputLocked(true);
  ChatState.currentCorrelationId = crypto.randomUUID();
  
  // 4. 送出 REST（狀態改變操作走 REST，見 00-tech-stack.md §4；WebSocket 只收 loading 進度推播）
  try {
    const res = await fetch("/api/what-if", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: ChatState.sessionId,
        content: text,
        correlation_id: ChatState.currentCorrelationId,
      }),
    });
    const envelope = await res.json();
    hideLoading();
    renderAIResponse(envelope.payload);
  } catch (err) {
    hideLoading();
    renderAIResponse({ intent_type: "error", summary: "系統暫時忙碌，請稍後再試", suggested_questions: [] });
  } finally {
    setInputLocked(false);
  }
}
```

### 4.8 面板收合/展開

```javascript
function togglePanel() {
  ChatState.isOpen = !ChatState.isOpen;
  const panel = document.getElementById("chat-panel");
  const fab = document.getElementById("chat-toggle-btn");
  
  if (ChatState.isOpen) {
    panel.classList.remove("collapsed");
    fab.style.display = "none";
    document.querySelector(".dashboard-main").style.marginRight = ChatState.panelWidth + "px";
  } else {
    panel.classList.add("collapsed");
    fab.style.display = "flex";
    document.querySelector(".dashboard-main").style.marginRight = "0";
  }
}
```

### 4.9 面板拖拉調整寬度

```javascript
function initResize() {
  const handle = document.querySelector(".chat-resize-handle");
  let isResizing = false;
  
  handle.addEventListener("mousedown", (e) => {
    isResizing = true;
    document.body.style.cursor = "col-resize";
  });
  
  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const newWidth = window.innerWidth - e.clientX;
    const clamped = Math.max(350, Math.min(550, newWidth));  // min 350, max 550
    ChatState.panelWidth = clamped;
    document.getElementById("chat-panel").style.width = clamped + "px";
    document.querySelector(".dashboard-main").style.marginRight = clamped + "px";
  });
  
  document.addEventListener("mouseup", () => {
    isResizing = false;
    document.body.style.cursor = "";
  });
}
```

---

## 五、WebSocket 連線管理

```javascript
function connectWebSocket() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  
  ws.onopen = () => {
    ChatState.wsConnection = ws;
    console.log("WebSocket connected");
  };
  
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleServerMessage(msg);
  };
  
  ws.onclose = () => {
    ChatState.wsConnection = null;
    // 3 秒後重連
    setTimeout(connectWebSocket, 3000);
  };
}

function handleServerMessage(msg) {
  // msg 是完整 Message Envelope；F6 只處理 message_type 前綴為 chat. 的訊息，
  // 其他模組（F1-F7）推播的 message_type 由各自的前端模組處理，F6 忽略即可。
  const payload = msg.payload || {};
  switch (msg.message_type) {
    case "chat.loading_start.v1":
      showLoading();
      break;
    case "chat.loading_step.v1":
      updateLoadingStep(payload.step, payload.status);
      break;
    case "chat.response.v1":
      // 冗餘推播（雙通道保底）：正常情況下 sendMessage() 的 fetch 已經直接渲染過同一份結果，
      // 這裡用 correlation_id 判斷是否已經渲染過，重複的話直接忽略，避免同一則回覆顯示兩次。
      if (payload.correlation_id !== ChatState.currentCorrelationId) return;
      hideLoading();
      renderAIResponse(payload);
      break;
    case "chat.input_lock.v1":
      // 冗餘：sendMessage() 已本地鎖定/解鎖，這裡是給非本人觸發鎖定的情境（例如另一個瀏覽器分頁）用
      setInputLocked(payload.locked);
      break;
    case "chat.system_status.v1":
      updateStatusBanner(payload);
      break;
    case "chat.session_cleared.v1":
      clearAllMessages();
      showDefaultQuickQuestions();
      break;
  }
}

function buildEnvelope(messageType, payload) {
  return {
    schema_version: "1.0",
    message_id: crypto.randomUUID(),
    correlation_id: ChatState.currentCorrelationId,
    message_type: messageType,
    source_module: "dashboard",
    target_module: "bedrock_advisor",
    generated_at: new Date().toISOString(),
    payload,
  };
}
```

---

## 六、自動捲動邏輯

```javascript
function appendToMessages(html) {
  const container = document.getElementById("chat-messages");
  const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
  
  container.insertAdjacentHTML("beforeend", html);
  
  // 只在使用者沒有往上捲的時候才自動捲到底
  if (isNearBottom) {
    container.scrollTop = container.scrollHeight;
  }
}
```

---

## 七、CSS 架構（分層）

```
frontend/
└── css/
    ├── chat-panel.css        # 面板容器、收合/展開、拖拉
    ├── chat-messages.css     # 氣泡、Avatar、時間戳
    ├── chat-cards.css        # Decision Card、SOP Badge、ETE Badge、Route Tag
    ├── chat-input.css        # 輸入框、送出按鈕、快捷問題
    ├── chat-loading.css      # Loading 動畫、步驟進度
    └── chat-variables.css    # CSS 變數（顏色、圓角、陰影）
```

CSS 變數集中管理，方便全域換色：

```css
:root {
  --chat-primary: #2563eb;
  --chat-danger: #dc2626;
  --chat-warning: #f59e0b;
  --chat-success: #16a34a;
  --chat-radius: 12px;
  --chat-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
  --chat-panel-width: 420px;
  --chat-panel-min: 350px;
  --chat-panel-max: 550px;
}
```

---

## 八、檔案結構（預期）

```
frontend/
├── css/
│   ├── chat-variables.css
│   ├── chat-panel.css
│   ├── chat-messages.css
│   ├── chat-cards.css
│   ├── chat-input.css
│   └── chat-loading.css
├── js/
│   ├── chat-app.js           # 主入口：初始化、WebSocket、事件綁定
│   ├── chat-render.js        # 渲染函式：renderUserMessage, renderAIResponse, renderDecisionCard
│   ├── chat-state.js         # ChatState 物件 + 收合/展開/拖拉邏輯
│   └── chat-utils.js         # escapeHtml, formatTime 等工具函式
└── index.html                # 或嵌入 Dashboard 的 template fragment
```

---

## 九、與 Dashboard 整合方式

F6 設計為可嵌入的獨立模組。整合時只需：

1. 在 Dashboard 的 HTML 中引入 F6 的 CSS 和 JS
2. 在 `<body>` 中放入 F6 的 HTML 結構（浮動按鈕 + 面板）
3. Dashboard 主區域加上 `class="dashboard-main"`（F6 的 JS 會操作它的 marginRight）

```html
<!-- 在 Dashboard HTML 尾部加入 -->
<link rel="stylesheet" href="/frontend/css/chat-variables.css">
<link rel="stylesheet" href="/frontend/css/chat-panel.css">
<!-- ...其他 CSS... -->

<div id="chat-toggle-btn" class="chat-fab">💬</div>
<div id="chat-panel" class="chat-panel collapsed">...</div>

<script src="/frontend/js/chat-utils.js"></script>
<script src="/frontend/js/chat-state.js"></script>
<script src="/frontend/js/chat-render.js"></script>
<script src="/frontend/js/chat-app.js"></script>
```

不需要修改 Dashboard 其他模組的程式碼。
