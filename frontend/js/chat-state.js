/**
 * ChatState 物件 + 收合/展開/拖拉邏輯。
 * 參考 spec：F6-chat-ui/design.md 第二節(2.2)、第四節(4.8/4.9)。
 */

const ChatState = {
  isOpen: false,
  isLocked: false,
  panelWidth: 420,
  messages: [],
  wsConnection: null,
  hasFirstMessage: false,
  currentCorrelationId: null,
  sessionId: null,
  assumptions: {},
  /**
   * 生效中的假設條件（畫成可個別移除的 chips）。
   *
   * [2026-08-02] 這份東西在此之前只存在於後端記憶體的 `Session.assumptions`：
   * 同 key 覆蓋、**不同 key 永久累加、永不過期**，而使用者完全看不出來累積了
   * 什麼。先問「如果基隆路塌」再問「光復南路現在怎樣」，第二題仍帶著基隆路的
   * 假設在算——畫面上沒有任何跡象。顯示出來就不會再有這種隱形狀態。
   *
   * 一律以後端回傳的 `active_assumptions` 為準，前端不自行推導：
   * LLM 這一輪可能又新增了假設，前端猜不到。
   */
  lastContextAsOf: null,
  /** 最近一次回答所依據的世界時刻，用來把更早的泡泡標成已過時。 */
  currentTraceId: null,
  /**
   * 使用者目前正在看的決策週期。
   *
   * [2026-08-01] 這個欄位**之前根本不存在**，而 `api.js::fetchWhatIf()` 的第四個
   * 參數就是 `currentTraceId`——`chat-app.js` 只傳了三個，所以它永遠是 undefined，
   * 後端收到的 `current_trace_id` 永遠是 null。
   *
   * 後果是整條連鎖：chatbot 拿不到 incident → 評估時刻掉到「資料集最新時刻」
   * （23:30）→ 用一個跟畫面差 80 分鐘的時間掃全市 → 命中十幾條全是背景 →
   * 路線與 ETE 在那個時刻算出完全不同的結果。
   *
   * 使用者的原話是「注入事件觸發報告書和 chatbot 問同個問題，給出的建議不同」。
   * 那不是 LLM 不穩定，是兩邊算的根本是不同時刻的世界。
   */
};

function initChatState() {
  ChatState.sessionId = generateId();
}

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

function initResize() {
  const handle = document.querySelector(".chat-resize-handle");
  let isResizing = false;

  handle.addEventListener("mousedown", () => {
    isResizing = true;
    document.body.style.cursor = "col-resize";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const newWidth = window.innerWidth - e.clientX;
    const clamped = Math.max(350, Math.min(550, newWidth));
    ChatState.panelWidth = clamped;
    document.getElementById("chat-panel").style.width = clamped + "px";
    document.querySelector(".dashboard-main").style.marginRight = clamped + "px";
  });

  document.addEventListener("mouseup", () => {
    isResizing = false;
    document.body.style.cursor = "";
  });
}
