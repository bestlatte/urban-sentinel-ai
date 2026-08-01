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
    header.innerHTML = `<span>交通策略諮詢顧問</span><button onclick="togglePanel()" style="background:none;border:none;font-size:1.2rem;cursor:pointer">✕</button>`;
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

  // 顯示 loading
  renderLoadingStart(["解析問題意圖", "檢索 SOP 條款", "呼叫決策模組", "計算 ETE", "組合回覆"]);

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
