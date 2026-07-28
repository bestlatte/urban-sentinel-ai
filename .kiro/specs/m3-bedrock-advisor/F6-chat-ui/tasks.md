# F6 — 對話視窗前端 | Tasks

> 前置文件：`specs/F6-chat-ui/requirements.md`、`specs/F6-chat-ui/design.md`
> 預估總工時：4~5 小時
> 前置條件：無（F6 可完全獨立開發，用 mock 資料測試）

> **[2026-07-28 總架構師補註]** 本文件下方沿用了 design.md 修正前的舊寫法（`static/` 目錄、`clear_session`／`system_status`／`chat_response` 等未套 Message Envelope 的訊息名稱、B級黃色）。design.md 已對齊 `00-tech-stack.md`／`02-data-contract.md` 修正，本文件按同樣規則理解即可，不必逐字比對：`static/` 一律讀作 `frontend/`；裸露的訊息名稱（如 `clear_session`）一律讀作對應的 `message_type`（如 `chat.clear_session.v1`），且需包一層 Envelope；B級顏色一律用橘色不用黃色。
>
> **[2026-07-28 二次補註]** `chat_message`（使用者送出的問題）不再是 WebSocket 訊息，改為 `POST /api/what-if`，同步等回應直接渲染（見 `00-tech-stack.md` §4「狀態改變操作走 REST」）；`chat_response` 對應的是這個 POST 的回應內容，而不是等 WebSocket 推播才顯示。只有 `clear_session` 維持走 WebSocket。Task 3、Task 9、Task 10、Task 11 下方寫「送 WebSocket `chat_message`」的地方，理解時改成「呼叫 `POST /api/what-if`」。

---

## Task 1：建立檔案結構與 CSS 變數

**做什麼：** 建立 `static/` 資料夾結構，定義全域 CSS 變數。

**具體步驟：**
1. 建立資料夾結構：`static/css/`、`static/js/`
2. 建立 `chat-variables.css`，定義所有顏色、圓角、陰影、寬度變數
3. 建立其他 5 個空的 CSS 檔（先佔位）
4. 建立 4 個空的 JS 檔（先佔位）

**完成標準：** 資料夾和檔案都存在，`chat-variables.css` 有完整的 `:root` 變數定義。

---

## Task 2：實作面板容器（收合/展開）

**做什麼：** 寫 `chat-panel.css` + `chat-state.js`，實作面板的收合/展開動畫。

**具體步驟：**
1. CSS：`.chat-panel` 固定在右側、`.collapsed` 隱藏、`.chat-fab` 浮動按鈕樣式
2. CSS：展開/收合的 transition 動畫（transform 或 width 過渡）
3. JS：`togglePanel()` 函式 — 切換 class + 調整 Dashboard marginRight
4. JS：綁定浮動按鈕 click → 展開、收合按鈕 click → 收合

**完成標準：** 打開 HTML，點浮動按鈕 → 面板滑出；點收合 → 面板滑回，浮動按鈕重現。

---

## Task 3：實作面板拖拉調整寬度

**做什麼：** 在面板左邊緣加上拖拉條，可調整面板寬度。

**具體步驟：**
1. CSS：`.chat-resize-handle` — 左邊緣 4px 寬的可拖拉區域，hover 時顯示 cursor
2. JS：`initResize()` — mousedown/mousemove/mouseup 事件監聽
3. 限制最小 350px、最大 550px
4. 拖拉時同步調整 Dashboard 主區域的 marginRight

**完成標準：** 拖拉左邊緣能調整面板寬度，Dashboard 區域跟著縮放，放開時停在當前位置。

---

## Task 4：實作 Header + Status Banner

**做什麼：** 寫 chat header（標題、清除按鈕、收合按鈕）和系統狀態 banner。

**具體步驟：**
1. HTML 結構：header icon + 文字 + actions 區域
2. CSS：header 固定在面板頂部、banner 緊接在下方
3. JS：清除按鈕 → `confirm()` → 送 WebSocket `clear_session`
4. JS：`updateStatusBanner(msg)` — 收到 `system_status` 時更新文字和顏色
5. CSS：三種級別的顏色 class（`.level-a` 紅、`.level-b` 黃、`.level-normal` 綠）

**完成標準：** header 顯示正確，手動呼叫 `updateStatusBanner({level:"A", description:"光復南路封閉", ete_minutes:90})` 能更新 banner。

---

## Task 5：實作訊息區基礎（使用者氣泡 + AI 氣泡）

**做什麼：** 寫 `chat-messages.css` + `chat-render.js` 中的基礎訊息渲染。

**具體步驟：**
1. CSS：`.msg`、`.msg-user`、`.msg-ai`、`.msg-bubble`、`.msg-avatar`、`.timestamp` 樣式
2. JS：`renderUserMessage(text)` — 產生使用者氣泡 HTML 並插入
3. JS：`renderAIResponse(data)` — 先只渲染摘要氣泡（Decision Card 留下一個 Task）
4. JS：`appendToMessages(html)` — 插入 + 自動捲動邏輯
5. JS：`escapeHtml()`、`formatTime()` 工具函式（放 `chat-utils.js`）

**完成標準：** 手動呼叫 `renderUserMessage("你好")` 和 `renderAIResponse({summary:"歡迎", intent_type:"chitchat", suggested_questions:[]})` 都能正確顯示。

---

## Task 6：實作 Decision Card 渲染

**做什麼：** 寫 `chat-cards.css` + `renderDecisionCard(data)` 函式。

**具體步驟：**
1. CSS：`.decision-card`、`.decision-card-header`、`.decision-card-body`、`.decision-row` 樣式
2. CSS：`.sop-badge`（多色版本）、`.route-tag`（blocked / primary）、`.ete-badge` 樣式
3. CSS：`.btn-explain`、`.explain-panel` 樣式
4. JS：`renderDecisionCard(data)` — 根據 data 有哪些欄位動態組裝卡片 HTML
5. JS：`toggleExplain(btn)` — 展開/收合推理過程面板

**完成標準：** 用 mock data 呼叫 `renderAIResponse(mockWhatifData)` 能顯示完整的 Decision Card，包含 SOP Badge、Route Tags、ETE Badge、Explain 按鈕（可點擊展開）。

---

## Task 7：實作快捷問題與延伸問題

**做什麼：** 實作預設快捷問題（初始狀態）+ AI 回覆後的延伸問題按鈕。

**具體步驟：**
1. HTML：預設快捷問題區域（5 個按鈕，hardcoded 內容）
2. CSS：`.quick-q` 按鈕樣式（pill 形、hover 變色）
3. JS：點擊快捷問題 → 呼叫 `sendMessage(text)`
4. JS：`renderSuggestedQuestions(questions)` — 在 AI 回覆下方生成按鈕
5. JS：第一則訊息送出後隱藏預設快捷問題（`hideDefaultQuickQuestions()`）
6. JS：清除對話後重新顯示預設快捷問題（`showDefaultQuickQuestions()`）

**完成標準：**
- 初始畫面顯示 5 個快捷問題
- 點一個 → 送出 → 快捷問題消失
- AI 回覆帶 3 個延伸問題 → 顯示在回覆下方
- 清除對話 → 預設快捷問題重新出現

---

## Task 8：實作 Loading 動畫

**做什麼：** 寫 `chat-loading.css` + loading 相關 JS。

**具體步驟：**
1. CSS：`.loading-indicator`、`.loading-dots` 跳動動畫、`.loading-steps` 步驟列表
2. CSS：步驟狀態：`.done`（綠色勾）、`.active`（藍色動畫）、無 class（灰色）
3. JS：`showLoading()` — 插入 loading 訊息
4. JS：`updateLoadingStep(step, status)` — 更新步驟狀態
5. JS：`hideLoading()` — 移除 loading 訊息

**完成標準：** 呼叫 `showLoading()` → 看到跳動點 + 空步驟列表 → 呼叫 `updateLoadingStep("檢索 SOP", "active")` → 看到步驟出現 → 呼叫 `hideLoading()` → 消失。

---

## Task 9：實作輸入區 + 鎖定邏輯

**做什麼：** 寫 `chat-input.css` + 輸入框、送出按鈕、鎖定邏輯。

**具體步驟：**
1. CSS：`.chat-input-area`、`.chat-input-wrapper`、`.chat-input`、`.chat-send-btn` 樣式
2. CSS：focus 時的 glow 效果、locked 時的灰化樣式
3. JS：`sendMessage()` — 取得輸入 → 渲染 user bubble → 送 WebSocket
4. JS：Enter 鍵綁定送出
5. JS：`setInputLocked(locked)` — 鎖定/解鎖輸入框和按鈕

**完成標準：** 輸入文字 → Enter 或點按鈕 → 送出 → 輸入框清空。鎖定時打字無反應、按鈕變灰。

---

## Task 10：實作 WebSocket 連線

**做什麼：** 寫 `chat-app.js` 的 WebSocket 連線與訊息分發。

**具體步驟：**
1. `connectWebSocket()` — 建立連線、綁定 onopen/onmessage/onclose
2. `handleServerMessage(msg)` — switch/case 分發不同 type 的訊息
3. 斷線重連：onclose 後 3 秒自動重試
4. 頁面載入時自動呼叫 `connectWebSocket()`

**完成標準：** 後端 FastAPI 跑起來時，前端能自動連上 WebSocket。手動在後端推一個 `chat_response` → 前端正確渲染。

---

## Task 11：整合測試（用 mock 後端）

**做什麼：** 寫一個簡易的 mock FastAPI WebSocket endpoint，驗證前端全流程。

**具體步驟：**
1. 建立 `scripts/mock_server.py`：一個只回固定回覆的 WebSocket server（`scripts/` 不在 `00-tech-stack.md` §3 固定結構內，這裡是理由：純開發期間驗證用的臨時工具，不隨專案交付，Demo 前刪除或忽略即可，不算「新增模組檔」）
2. 收到任何 `chat_message` → 等 2 秒 → 回傳一個完整的 mock `chat_response`
3. 中間推 `loading_start` + 幾個 `loading_step`
4. 用瀏覽器打開 F6，完整走一遍：
   - 點浮動按鈕展開
   - 點快捷問題送出
   - 看到 loading → Decision Card → 延伸問題
   - 點延伸問題再送一輪
   - 拖拉寬度
   - 清除對話

**完成標準：** 上述流程全部順暢，無 JS 錯誤，視覺效果與 prototype 一致。

---

## Task 12：視覺微調與 Demo 準備

**做什麼：** 最終視覺打磨，確保投影到大螢幕時效果良好。

**具體步驟：**
1. 調整字體大小：確保投影時文字清晰
2. 檢查深色/淺色對比度（WCAG AA 標準）
3. 測試不同視窗寬度（1920px / 1440px / 1280px）
4. 確認動畫流暢度（transition 時間、loading 動畫）
5. 清理不用的 CSS（如果有的話）

**完成標準：** 在 1920x1080 和 1440x900 兩種解析度下都看起來正常且好看。

---

## 執行順序建議

```
基礎結構（不需要後端）：
  Task 1 → Task 2 → Task 3 → Task 4

訊息渲染（不需要後端，用 JS console 測試）：
  Task 5 → Task 6 → Task 7 → Task 8 → Task 9

連線與整合：
  Task 10 → Task 11

最後打磨：
  Task 12
```

**F6 完全不依賴其他模組**，可以第一天就開始做。用 mock server（Task 11）就能獨立測試整個前端。等後端 W1/W2 做好再接上真實 WebSocket。
