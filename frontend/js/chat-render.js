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
      <div class="msg-time">${formatTime(new Date().toISOString())}</div>
    </div>`;
  appendToMessages(html);
}

/** 這些 intent 只有文字回覆，沒有可畫的結構化資料，不要生一張空卡片。 */
const _CARDLESS_INTENTS = new Set(["chitchat", "trace_answer", "error"]);

function renderAIResponse(data) {
  let html = `<div class="msg msg-ai">`;
  // [2026-08-01] LLM 的回覆本來就是 Markdown，原本用 escapeHtml 直接輸出，
  // 於是 **粗體**、## 標題、| 表格 | 全部以原始字元顯示。renderMarkdown()
  // 內部一樣會先逃逸再套語法，安全性不變。
  html += `<div class="msg-bubble md">${renderMarkdown(data.summary || "")}</div>`;

  if (data.intent_type && !_CARDLESS_INTENTS.has(data.intent_type)) {
    html += renderDecisionCard(data);
  }

  // 後續風險推演時間軸（若後端有帶）。跟 Dashboard 用同一支渲染函式，
  // 兩處看到的圖必然一致。
  if (typeof renderRiskTimeline === "function" && data.projected_risks) {
    html += renderRiskTimeline(data.projected_risks);
  }

  // 決策軌跡獨立於卡片之外渲染。
  //
  // [2026-08-01] 回溯追問（trace_answer）在 _CARDLESS_INTENTS 裡不畫卡片——
  // 它沒有 What-if 重算結果，硬畫會生出一張空殼。但它**最需要**顯示軌跡：
  // 「延吉街為什麼不能走」問的就是當初實際跑了哪些步驟。所以軌跡放在卡片外面，
  // 只要後端帶了 trace_steps 就畫。
  if (typeof renderDecisionTrace === "function") {
    html += renderDecisionTrace(data.trace_steps);
  }

  html += renderSuggestedQuestions(data.suggested_questions);
  html += `<div class="msg-time">${formatTime(new Date().toISOString())}</div>`;
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

function renderLoadingStart(steps) {
  const html = `<div class="msg msg-ai" id="loading-msg">
    <div class="loading-container">
      <div class="loading-dots"><span></span><span></span><span></span></div>
      <div class="loading-steps">${steps.map((s, i) =>
        `<div class="loading-step${i === 0 ? " active" : ""}">${escapeHtml(s)}</div>`
      ).join("")}</div>
    </div>
  </div>`;
  appendToMessages(html);
}

function removeLoading() {
  const el = document.getElementById("loading-msg");
  if (el) el.remove();
}
