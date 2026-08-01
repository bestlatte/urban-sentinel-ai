/**
 * 渲染函式：renderUserMessage / renderAIResponse / renderDecisionCard。
 * 參考 spec：F6-chat-ui/design.md 第四節(4.3-4.5)。
 * B 級用橘色（var(--level-b)），不是黃色。
 */

function appendToMessages(html) {
  const container = document.getElementById("chat-messages");
  container.insertAdjacentHTML("beforeend", html);
  container.scrollTop = container.scrollHeight;
}

function renderUserMessage(text) {
  const html = `
    <div class="msg msg-user">
      <div class="msg-bubble">${escapeHtml(text)}</div>
      <div class="msg-time">${formatTime(nowSimAwareISO())}</div>
    </div>`;
  appendToMessages(html);
}

/** 這些 intent 沒有工具結果可畫，硬畫 `renderDecisionCard()` 只會生出一張
 *  只有標題的空殼。`report_followup` 也在內——它答得完整，但那份完整來自
 *  事實區塊而不是工具回傳，卡片裡該填的欄位一個都沒有。 */
const _CARDLESS_INTENTS = new Set([
  "chitchat", "trace_answer", "error", "report_followup",
]);

/** 這些 intent 連附件（後續風險推演時間軸）都不該有。
 *
 *  跟 `_CARDLESS_INTENTS` 差在 `report_followup`：「這起事件該怎麼處理」
 *  沒有卡片可畫，但那張推演圖正是使用者要的答案。
 *
 *  後端 `orchestrator._STRUCTURED_INTENTS` 是同一條線的另一側。 */
const _ATTACHMENTLESS_INTENTS = new Set(["chitchat", "trace_answer", "error"]);

function renderAIResponse(data) {
  let html = `<div class="msg msg-ai">`;
  // [2026-08-01] LLM 的回覆本來就是 Markdown，原本用 escapeHtml 直接輸出，
  // 於是 **粗體**、## 標題、| 表格 | 全部以原始字元顯示。renderMarkdown()
  // 內部一樣會先逃逸再套語法，安全性不變。
  html += `<div class="msg-bubble md">${renderMarkdown(data.summary || "")}</div>`;

  // [2026-08-02] 所有結構化區塊（決策卡片、後續風險推演）共用同一道守衛。
  //
  // 原本風險時間軸畫在守衛**外面**，判斷只有「後端有沒有帶 projected_risks」——
  // 而後端 `_attach_trace()` 是無條件掛的。結果使用者問「你是誰」，回覆下面
  // 跟著一張後續風險推演時間軸。閒聊本來就沒有情境可推演，那張圖講的是別的
  // 事件，出現在這裡只會讓人以為系統把問題聽成別的東西了。
  //
  // 後端那側也已經改成依 intent 過濾（見 `orchestrator._attach_trace()`），
  // 這裡是第二道保險——payload 從哪條路徑來都不會漏。
  if (data.intent_type && !_CARDLESS_INTENTS.has(data.intent_type)) {
    html += renderDecisionCard(data);
  }

  // 後續風險推演時間軸（若後端有帶）。跟 Dashboard 用同一支渲染函式，
  // 兩處看到的圖必然一致。
  if (
    data.intent_type &&
    !_ATTACHMENTLESS_INTENTS.has(data.intent_type) &&
    typeof renderRiskTimeline === "function" &&
    data.projected_risks
  ) {
    html += renderRiskTimeline(data.projected_risks);
  }

  // [2026-08-02 移除決策軌跡] 對話框裡不再顯示決策軌跡。
  //
  // 它原本畫在這裡（卡片之外，只要後端帶了 `trace_steps` 就畫），但那份軌跡
  // 是稽核資料——誰在第幾步呼叫了什麼工具、耗時幾毫秒。在幾百像素寬的側邊
  // 對話框裡，它把真正的答案往下擠了一整屏，而指揮官要的是可以立刻行動的
  // 結論。決策的「為什麼」在 Report 頁的「決策推理過程」講得完整得多
  // （`decision-reasoning.js`），那裡有版面、也有對照的原始依據。

  html += renderSuggestedQuestions(data.suggested_questions);
  html += `<div class="msg-time">${formatTime(nowSimAwareISO())}</div>`;
  html += `</div>`;
  appendToMessages(html);
}

function renderDecisionCard(data) {
  let card = `<div class="decision-card">`;

  card += `<div class="card-title">${
    data.intent_type === "whatif_simulation" ? "What-if 模擬結果" : "SOP 查詢結果"
  }</div>`;

  // 假想事故 + 嚴重度並列比較，放在最上面。
  //
  // 它回答的是「你這個假設，系統怎麼理解的」——包含評估時刻與嚴重度，
  // 兩者都會直接改變下面所有數字。使用者要先確認系統理解對了，
  // 再往下看推演與解方才有意義。
  if (typeof renderSeverityOptions === "function" && data.hypothetical_incident) {
    card += renderSeverityOptions(data.hypothetical_incident, data.severity_options);
  }

  // 參考條文（RAG 語意檢索）
  //
  // [2026-08-01] 標上「參考條文」而不是「觸發條款」。這兩個是**不同來源**：
  //
  //   triggered_sops ← Bedrock 知識庫語意檢索：「跟這個問題語意上相關的 SOP」
  //   rule_hits      ← 規則引擎數值比對：「數值上真的跨過門檻的條款」
  //
  // 原本兩者並排且都沒標來源，於是出現過這種畫面：標題掛「SOP-2 車禍與路障
  // 應變」，下面的命中條款裡卻一條 SOP-2 都沒有——看起來像系統自相矛盾，
  // 其實是「語意上相關」與「數值上命中」本來就會不一樣，而且**應該**不一樣。
  //
  // 檢索到的條文若同時也在規則命中裡，加一個記號，讓兩者的關係一眼可見。
  if (data.triggered_sops && data.triggered_sops.length > 0) {
    const hitSections = new Set();
    (data.judgment_steps || []).forEach(st => {
      if (st.stage === "rules") {
        (st.items || []).forEach(it => {
          const m = /SOP-(\d+)/.exec(it.clause_id || "");
          if (m) hitSections.add(Number(m[1]));
        });
      }
    });

    card += `<div class="sop-ref-block">`;
    card += `<div class="sop-ref-label">參考條文<span>知識庫語意檢索，非數值命中</span></div>`;
    data.triggered_sops.forEach(sop => {
      const alsoHit = hitSections.has(sop.section_number);
      const cls = `sop-badge sop-${sop.section_number}${alsoHit ? " sop-also-hit" : ""}`;
      const mark = alsoHit ? `<span class="sop-hit-mark" title="此條款同時也數值命中">●</span>` : "";
      card += `<span class="${cls}">${mark}SOP-${sop.section_number} ${escapeHtml(sop.title)}</span>`;
    });
    card += `</div>`;
  }

  // 推理鏈（假設 → 命中條款 → 路線 → ETE）
  //
  // [2026-08-01] 取代原本的三段式呈現：`judgment_basis` 純文字（多行 Markdown
  // 被 escapeHtml 壓成一坨）、`route_impact` 標籤（吃到物件變成 [object Object]）、
  // 以及只有 SOP 條文的「查看推理過程」。現在改讀後端的 `judgment_steps`，
  // 由 reasoning-chain.js 畫成有比例條與改前改後對照的圖。
  const chainHtml = typeof renderReasoningChain === "function"
    ? renderReasoningChain(data)
    : "";
  card += chainHtml;

  // 純文字判斷依據只在畫不出推理鏈時當退路（例如舊版 payload 沒有
  // judgment_steps）。有圖就不要再貼一次同樣的內容。
  if (!chainHtml && data.judgment_basis) {
    card += `<div class="md" style="font-size:0.75rem;color:var(--text-muted);margin-bottom:6px">${renderMarkdown(data.judgment_basis)}</div>`;
  }

  // 預期動作
  if (data.expected_actions && data.expected_actions.length > 0) {
    card += `<div class="rc-actions"><div class="rc-actions-title">建議動作</div>`;
    data.expected_actions.forEach(action => {
      card += `<div class="rc-action">${escapeHtml(action)}</div>`;
    });
    card += `</div>`;
  }

  // 情境建議書（方案B：使用者明確要求出報告時才有）
  if (data.scenario_report) {
    card += `<details class="rc-report"><summary>假設情境交控建議書</summary>
      <div class="md">${renderMarkdown(data.scenario_report)}</div>
    </details>`;
  }

  // SOP 條文原文（摺疊，預設收起——條文很長，不該預設佔版面）
  if (data.triggered_sops && data.triggered_sops.length > 0) {
    card += `<details class="rc-sop-detail"><summary>SOP 條文原文</summary>`;
    data.triggered_sops.forEach(sop => {
      card += `<p><strong>SOP-${sop.section_number}：${escapeHtml(sop.title)}</strong><br>${escapeHtml(sop.content || "")}</p>`;
    });
    card += `</details>`;
  }

  card += `</div>`;
  return card;
}

function renderSuggestedQuestions(questions) {
  if (!questions || questions.length === 0) return "";
  let html = `<div class="chat-quick-questions" style="margin-top:8px">`;
  questions.forEach(q => {
    html += `<button class="quick-q" onclick="sendQuickQuestion(this)">${escapeHtml(q)}</button>`;
  });
  html += `</div>`;
  return html;
}

function sendQuickQuestion(btn) {
  const text = btn.textContent;
  if (typeof sendMessage === "function") sendMessage(text);
}

/**
 * 思考中的步驟文字。
 *
 * [2026-08-02] 原本這份清單在前後端各寫一次（`chat-app.js::sendMessage()` 的
 * 呼叫端一份、`src/agent/loading.py::LOADING_STEPS` 一份），改一邊另一邊不會動。
 * 前端這側統一從這裡取。
 */
const LOADING_STEPS = ["解析問題意圖", "檢索 SOP 條款", "呼叫決策模組", "計算 ETE", "組合回覆"];

/**
 * 畫出「思考中」的泡泡。
 *
 * [2026-08-02 修正：畫面上同時出現兩個思考 UI]
 * ------------------------------------------
 * 原本這支函式會被呼叫**兩次**：
 *
 *   1. `chat-app.js::sendMessage()` 本地先畫一個
 *   2. 後端 `chat.loading_start.v1` 推播回來，`ws.js` 又畫一個
 *      （那裡的守衛是 `correlation_id !== currentCorrelationId` 就 return，
 *       也就是**相符時才畫**——而本地那次用的正是同一個 correlation_id）
 *
 * 兩個節點掛同一個 `id="loading-msg"`，`removeLoading()` 的 `getElementById`
 * 只拿得到第一個，第二個就永遠留在對話串裡。
 *
 * 現在改成冪等：已經有一個在跑就不再畫。本地渲染是唯一來源（REST 是同步的，
 * 本地畫最即時，也不受 WS 斷線影響），WS 推播退化成純粹的保險。
 */
function renderLoadingStart(steps) {
  if (document.querySelector(".chat-loading-msg")) return;

  const list = steps && steps.length ? steps : LOADING_STEPS;
  const html = `<div class="msg msg-ai chat-loading-msg" id="loading-msg">
    <div class="loading-container">
      <div class="loading-dots"><span></span><span></span><span></span></div>
      <div class="loading-steps">${list.map((s, i) =>
        `<div class="loading-step${i === 0 ? " active" : ""}">${escapeHtml(s)}</div>`
      ).join("")}</div>
    </div>
  </div>`;
  appendToMessages(html);
}

/** 清掉所有思考中泡泡。用 querySelectorAll 而不是 getElementById——
 *  萬一因為任何理由殘留了第二個，這裡要能一併收乾淨。 */
function removeLoading() {
  document.querySelectorAll(".chat-loading-msg").forEach(el => el.remove());
}
