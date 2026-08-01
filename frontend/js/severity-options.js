/**
 * 嚴重度並列比較表。
 *
 * 為什麼是「並列」而不是「回問一句」
 * ----------------------------------
 * 指揮官說「如果市民大道四段封閉會怎樣」時，沒有講嚴重度。而嚴重度直接決定
 * ETE——依 SOP-7，base_clearance 是 Critical 60 / High 40 / Medium 20 分鐘，
 * 加上壅塞加權後實測差到 40 分鐘（88 / 68 / 48）。那個差距會改變調度決策。
 *
 * 三種處理方式：
 *   猜一個        → 給出他沒同意過的 ETE，而且畫面上不會有任何跡象顯示是猜的
 *   回問一句      → 他要再等一輪 LLM 往返才看得到答案
 *   三種都算並列  → 他掃一眼就知道自己面對的是哪一種  ← 選這個
 *
 * 這張表刻意做成「可掃視」而不是「可閱讀」：欄位對齊、數字等寬，指揮官要的是
 * 在兩秒內比較三行，不是讀三段敘述。
 */

/** 嚴重度 → 色階。由重到輕，跟應變等級的紅橘語彙一致。 */
const _SEV_CLASS = {
  Critical: "sev-critical",
  High: "sev-high",
  Medium: "sev-medium",
};

/**
 * @param {object} hypo  hypothetical_incident 區塊
 * @param {Array}  opts  severity_options 陣列（未指定嚴重度時才有）
 */
function renderSeverityOptions(hypo, opts) {
  if (!hypo) return "";

  let html = `<div class="sev-block">`;

  // 標頭：先講清楚這是假想情境，不是真的發生了
  html += `<div class="sev-head">
    <span class="sev-title">假設情境：${escapeHtml(hypo.segment_name || hypo.segment_id || "")}封閉</span>
    <span class="sev-asof">評估時刻 ${escapeHtml(hypo.as_of || "")}${
      hypo.as_of_reason ? `・${escapeHtml(hypo.as_of_reason)}` : ""
    }</span>
  </div>`;

  // 疊加情境要把基準講出來。少了這一句，使用者會以為系統忘了那起
  // 還在進行中的真實事件——而所有數字其實都是建立在它之上算的。
  if (hypo.base_incident) {
    const b = hypo.base_incident;
    html += `<div class="sev-base">
      疊加於進行中事件
      <strong>${escapeHtml(b.segment_name || b.segment_id || "")}</strong>
      （${escapeHtml(b.event_id || "")}）尚未排除
    </div>`;
  }

  if (!opts || opts.length === 0) {
    // 使用者已經講明嚴重度，沒有選項要挑
    html += `</div>`;
    return html;
  }

  html += `<div class="sev-note">未指定嚴重程度，以下並列三種情況供研判</div>`;

  html += `<div class="sev-table">
    <div class="sev-row sev-row-head">
      <span class="sev-c-level">程度</span>
      <span class="sev-c-ete">預計排除</span>
      <span class="sev-c-route">主要改道</span>
      <span class="sev-c-risk">後續風險</span>
    </div>`;

  opts.forEach(o => {
    const cls = _SEV_CLASS[o.severity] || "";
    const risk = o.risk_count
      ? `${o.risk_count} 項・最快 ${escapeHtml(o.first_risk_at || "")}`
      : "無新增壓力";
    html += `<div class="sev-row ${cls}">
      <span class="sev-c-level"><span class="sev-dot"></span>${escapeHtml(o.severity_label || o.severity)}</span>
      <span class="sev-c-ete">${o.ete_minutes != null ? escapeHtml(String(o.ete_minutes)) + " 分" : "—"}</span>
      <span class="sev-c-route">${escapeHtml(o.primary_route || "無可行路線")}</span>
      <span class="sev-c-risk">${risk}${
        o.no_safe_route ? `<span class="sev-warn">替代路線全滿</span>` : ""
      }</span>
    </div>`;
  });

  html += `</div>`;

  // 下面顯示的推演與解方是用哪一種算的，必須講明——否則使用者會以為
  // 那是「這個假設」的唯一答案，而其實是三選一裡最保守的那個。
  html += `<div class="sev-active">以下推演與處置建議以「${escapeHtml(
    opts[0].severity_label || opts[0].severity
  )}」計算（最保守）。實際程度不同請對照上表調整。</div>`;

  html += `</div>`;
  return html;
}
