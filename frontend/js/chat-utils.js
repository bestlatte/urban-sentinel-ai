/**
 * 工具函式：escapeHtml / formatTime。
 * 參考 spec：m3-bedrock-advisor/F6-chat-ui/design.md 第四節(4.3)。
 */

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(isoString) {
  if (!isoString) return "";
  const d = new Date(isoString);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

/**
 * 前端的「現在幾點」單一來源。對應後端的 `src/clock.py::now()`。
 *
 * [2026-08-02] 畫面上原本混著兩種時間：模擬器跑到 22:10，對話氣泡與活動紀錄
 * 卻蓋著真實時間（Demo 當下可能是下午三點）。同一則回覆裡「事故發生於 22:10」
 * 與時間戳「15:42」並排，看起來像系統時鐘壞了。
 *
 * 模擬器沒啟用時退回真實時間——那時候兩者本來就是同一件事。
 *
 * **唯一不該用這支的地方**是 Header `System Online` 旁邊的時鐘
 * （`app.js::initHeaderClock()`）：那盞燈講的是這台機器在不在線，
 * 不是被模擬的世界現在幾點。
 */
function nowSimAware() {
  if (typeof SimState !== "undefined" && SimState.enabled && SimState.currentTime) {
    return SimState.currentTime;
  }
  return new Date();
}

/** `nowSimAware()` 的 ISO 字串版，給只吃字串的呼叫端（如 formatTime）。 */
function nowSimAwareISO() {
  return nowSimAware().toISOString();
}

function generateId() {
  return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
}
