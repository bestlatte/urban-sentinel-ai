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
