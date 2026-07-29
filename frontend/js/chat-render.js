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

function renderAIResponse(data) {
  let html = `<div class="msg msg-ai">`;
  html += `<div class="msg-bubble">${escapeHtml(data.summary || "")}</div>`;

  if (data.intent_type && data.intent_type !== "chitchat") {
    html += renderDecisionCard(data);
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

  // 觸發條款
  if (data.triggered_sops && data.triggered_sops.length > 0) {
    card += `<div style="margin-bottom:8px">`;
    data.triggered_sops.forEach(sop => {
      const cls = `sop-badge sop-${sop.section_number}`;
      card += `<span class="${cls}">SOP-${sop.section_number} ${escapeHtml(sop.title)}</span>`;
    });
    card += `</div>`;
  }

  // 判定依據
  if (data.judgment_basis) {
    card += `<div style="font-size:0.8rem;color:#64748b;margin-bottom:6px">${escapeHtml(data.judgment_basis)}</div>`;
  }

  // 預期動作
  if (data.expected_actions && data.expected_actions.length > 0) {
    card += `<div style="font-size:0.8rem;margin-bottom:6px">`;
    data.expected_actions.forEach((action, i) => {
      card += `${i + 1}. ${escapeHtml(action)}<br>`;
    });
    card += `</div>`;
  }

  // 路網影響
  if (data.route_impact) {
    card += `<div style="margin-bottom:6px">`;
    if (data.route_impact.blocked) {
      data.route_impact.blocked.forEach(r => {
        card += `<span class="route-tag blocked">${escapeHtml(r)}</span>`;
      });
    }
    if (data.route_impact.primary) {
      card += `<span class="route-tag primary">${escapeHtml(data.route_impact.primary)}</span>`;
    }
    if (data.route_impact.secondary) {
      card += `<span class="route-tag secondary">${escapeHtml(data.route_impact.secondary)}</span>`;
    }
    card += `</div>`;
  }

  // ETE
  if (data.ete) {
    card += `<span class="ete-badge">ETE ${data.ete.minutes} 分鐘</span>`;
  }

  // Explain（SOP 原文摺疊）
  if (data.triggered_sops && data.triggered_sops.length > 0) {
    card += `<details style="margin-top:8px;font-size:0.75rem"><summary style="cursor:pointer">查看推理過程</summary>`;
    data.triggered_sops.forEach(sop => {
      card += `<p><strong>SOP-${sop.section_number}：${escapeHtml(sop.title)}</strong><br>${escapeHtml(sop.content || "")}</p>`;
    });
    if (data.ete && data.ete.formula) {
      card += `<p><strong>ETE：</strong>${escapeHtml(data.ete.formula)}</p>`;
    }
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
