/**
 * F6 對話主邏輯：sendMessage() 走 REST POST /api/what-if，不走 WS。
 * 參考 spec：F6-chat-ui/design.md 第三節（修正版：問題走 REST，WS 只收推播）。
 */

function initChatApp() {
  initChatState();
  initResize();

  const fab = document.getElementById("chat-toggle-btn");
  if (fab) fab.addEventListener("click", togglePanel);

  const header = document.getElementById("chat-header");
  if (header) {
    // 「重新開始」是這個對話框唯一的話題邊界。
    //
    // [2026-08-02] 在此之前完全沒有出口：後端的 `clear_session()` 和前端的
    // `sendWsClearSession()` 兩邊都寫好了，但**沒有任何一行程式呼叫它**，
    // 使用者想換一個完全不同的話題只能重整整個頁面。而對話是一路累積的
    // ——尤其是假設條件——所以「換個話題」實際上會把舊假設帶進新問題裡算。
    header.innerHTML = `
      <span>交通策略諮詢顧問</span>
      <span style="display:flex;align-items:center;gap:4px">
        <button id="chat-reset-btn" onclick="resetChatSession()" title="清除對話與所有假設條件，重新開始"
          style="background:none;border:1px solid var(--chat-border,rgba(0,0,0,.15));border-radius:6px;
                 font-size:0.72rem;padding:3px 8px;cursor:pointer;color:inherit">↻ 重新開始</button>
        <button onclick="togglePanel()" style="background:none;border:none;font-size:1.2rem;cursor:pointer">✕</button>
      </span>`;
  }

  const inputArea = document.getElementById("chat-input-area");
  if (inputArea) {
    inputArea.innerHTML = `
      <input type="text" id="chat-input" placeholder="輸入問題（如：如果BL17到40000人...）" />
      <button id="chat-send-btn" onclick="sendMessage()">送出</button>
    `;
    const input = document.getElementById("chat-input");
    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          sendMessage();
        }
      });
    }
  }

  // 顯示預設快捷問題
  renderInitialQuickQuestions();
}

/**
 * 重新開始：清掉伺服器端的 session、畫面訊息、假設條件與週期綁定。
 *
 * 換一個新的 `sessionId` 而不是沿用舊的——後端 `clear_session()` 是把整個
 * Session 物件 pop 掉，若這時有一個還在飛的請求用舊 id 回來，`record_response()`
 * 會重新建立那個 session 並把剛清掉的東西寫回去。換 id 就沒有這個競態。
 */
function resetChatSession() {
  if (typeof sendWsClearSession === "function") sendWsClearSession();

  ChatState.sessionId = generateId();
  ChatState.currentCorrelationId = null;
  ChatState.currentTraceId = null;
  ChatState.hasFirstMessage = false;
  ChatState.messages = [];
  ChatState.assumptions = {};
  ChatState.lastContextAsOf = null;

  const box = document.getElementById("chat-messages");
  if (box) box.innerHTML = "";
  renderAssumptionChips({});

  const qc = document.getElementById("chat-quick-questions");
  if (qc) qc.style.display = "";
  renderInitialQuickQuestions();
}

/**
 * 生效中的假設條件 chips。空的時候整條列隱藏，不佔版面。
 *
 * 每顆 chip 可以單獨移除——比「整段對話重來」精細得多。使用者常常只是想
 * 拿掉其中一個假設繼續問，不需要連前面問過的東西一起丟。
 */
function renderAssumptionChips(assumptions) {
  const el = document.getElementById("chat-assumptions");
  if (!el) return;

  ChatState.assumptions = assumptions || {};
  const keys = Object.keys(ChatState.assumptions);
  if (!keys.length) {
    el.innerHTML = "";
    el.style.display = "none";
    return;
  }

  el.style.display = "";
  el.innerHTML =
    `<span class="chat-assumptions-label">生效假設</span>` +
    keys.map(k => `
      <span class="chat-assumption-chip">
        ${escapeHtml(_assumptionLabel(k, ChatState.assumptions[k]))}
        <button title="移除這項假設" onclick="dropAssumption('${escapeHtml(k)}')">×</button>
      </span>`).join("");
}

/** `RD_TPE_004.saturation_score = 0.98` → 「市民大道四段 飽和度 0.98」。 */
function _assumptionLabel(key, value) {
  const [entity, field] = String(key).split(".");
  const name = (typeof _getSegmentName === "function" && _getSegmentName(entity)) || entity;
  const fieldLabels = {
    saturation_score: "飽和度",
    lane_status: "車道狀態",
    avg_speed: "平均速率",
    vehicle_count: "車輛數",
    user_count: "人數",
    growth_rate: "成長率",
    roaming_user_pct: "漫遊比率",
    capacity_vph: "每小時容量",
  };
  return `${name} ${fieldLabels[field] || field || ""} ${value}`.trim();
}

async function dropAssumption(key) {
  try {
    const resp = await fetch("/api/chat/assumptions/drop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: ChatState.sessionId, key }),
    });
    const data = await resp.json();
    if (data.status === "ok") renderAssumptionChips(data.active_assumptions || {});
  } catch (err) {
    console.warn("[對話] 移除假設失敗", err);
  }
}

function renderInitialQuickQuestions() {
  const container = document.getElementById("chat-quick-questions");
  if (!container) return;
  const defaults = ["目前系統是什麼應變等級？", "替代路線還有容量嗎？", "ETE 預計多久恢復？"];
  container.innerHTML = defaults.map(q =>
    `<button class="quick-q" onclick="sendQuickQuestion(this)">${escapeHtml(q)}</button>`
  ).join("");
}

async function sendMessage(text) {
  const input = document.getElementById("chat-input");
  if (!text) {
    text = input ? input.value.trim() : "";
  }
  if (!text || ChatState.isLocked) return;

  // 清空輸入框
  if (input) input.value = "";

  // 隱藏快捷問題（第一次送出後）
  if (!ChatState.hasFirstMessage) {
    ChatState.hasFirstMessage = true;
    const qc = document.getElementById("chat-quick-questions");
    if (qc) qc.style.display = "none";
  }

  // 渲染使用者訊息
  renderUserMessage(text);

  // 鎖定輸入
  ChatState.isLocked = true;
  ChatState.currentCorrelationId = generateId();

  // 顯示 loading（步驟文字由 chat-render.js 的 LOADING_STEPS 統一提供）
  renderLoadingStart(LOADING_STEPS);

  try {
    // 走 REST，不走 WS
    // 第四個參數是使用者正在看的決策週期。漏掉它就是「報告書與 chatbot
    // 給出不同建議」的根因——見 ChatState.currentTraceId 的說明。
    const data = await fetchWhatIf(
      text,
      ChatState.sessionId,
      ChatState.currentCorrelationId,
      ChatState.currentTraceId
    );

    removeLoading();

    if (data.status === "ok" && data.payload) {
      // 假設 chips 與過時標記由 `renderAIResponse()` 統一處理——
      // 回覆有三條進入路徑，只在這裡做另外兩條會漏掉。
      renderAIResponse(data.payload);
    } else if (data.errors) {
      renderAIResponse({ intent_type: "error", summary: data.errors[0].message, suggested_questions: [] });
    } else {
      renderAIResponse({ intent_type: "error", summary: "系統暫時忙碌，請稍後再試", suggested_questions: [] });
    }
  } catch (err) {
    removeLoading();
    renderAIResponse({ intent_type: "error", summary: "網路錯誤，請確認連線狀態", suggested_questions: [] });
  }

  // 解鎖
  ChatState.isLocked = false;
  ChatState.currentCorrelationId = null;
}
