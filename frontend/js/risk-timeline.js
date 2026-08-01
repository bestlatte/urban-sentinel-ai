/**
 * 後續風險推演的圖形化推理鏈。
 *
 * 要回答的問題
 * ------------
 * 建議書原本止於「現在該做什麼」。這支檔案畫的是「**這麼做之後會怎樣**」：
 *
 *     現在 22:10          22:20              22:35
 *     ─────●───────────────●──────────────────●─────▶
 *      決策執行        市民大道四段        市民大道四段
 *      改道 RD_004      → B 級             → A 級
 *                      0.78 ▸ 0.86        0.78 ▸ 0.98
 *                      ▸ 預先啟動長綠燈    ▸ 觸發替代路網引導
 *
 * 為什麼要畫成時間軸而不是列表
 * ----------------------------
 * 這些風險的核心資訊是**還有多久**。指揮官要決定的是「先處理哪一個、什麼時候
 * 動手」，而列表把所有項目呈現成同等距離的並列，時間差異被壓平了。
 * 時間軸讓「10 分鐘後」跟「45 分鐘後」在視覺上就有差別。
 *
 * 資料全部來自後端 `risk_projection.py` 的確定性運算，前端不做任何推算——
 * 這裡只負責把已經算好的數字放到正確的位置上。
 */

/** 風險等級 → 顏色類別。跟 Dashboard 的應變等級用同一套語彙。 */
const _RISK_LEVEL_CLASS = { A: "risk-a", B: "risk-b" };

function _riskPct(minutes, horizon) {
  const h = horizon || 60;
  return Math.max(0, Math.min(100, (minutes / h) * 100));
}

/**
 * 主入口：把 `projected_risks` 畫成時間軸。
 * 沒有風險時回一句「未預期產生新的路網壓力」，不回空字串——
 * 「算過了，沒問題」跟「沒算」對指揮官是兩件事。
 */
function renderRiskTimeline(projection) {
  if (!projection) return "";

  const risks = projection.risks || [];
  const horizon = projection.horizon_minutes || 60;

  let html = `<div class="risk-projection">`;
  html += `<div class="risk-head">
    <span class="risk-title">後續風險推演</span>
    <span class="risk-horizon">往後 ${escapeHtml(String(horizon))} 分鐘</span>
  </div>`;

  // 升級判斷放最前面：它代表「單靠改道解決不了」，是最重要的一句話
  if (projection.no_safe_route && projection.escalation) {
    html += `<div class="risk-escalation">
      <strong>單靠路網分流無法解決</strong>
      <div>${escapeHtml(projection.escalation)}</div>
    </div>`;
  }

  if (risks.length === 0) {
    html += `<div class="risk-none">依容量轉移模型推演，此決策未預期產生新的路網壓力。</div>`;
    html += _renderAssumptions(projection);
    html += `</div>`;
    return html;
  }

  // --- 時間軸本體 ---
  html += `<div class="risk-axis">
    <div class="risk-axis-line"></div>
    <div class="risk-marker risk-now" style="left:0%">
      <span class="risk-dot"></span>
      <span class="risk-marker-label">現在</span>
    </div>`;
  risks.forEach((r, i) => {
    const pct = _riskPct(r.at_minutes, horizon);
    const cls = _RISK_LEVEL_CLASS[r.level] || "";
    html += `<div class="risk-marker ${cls}" style="left:${pct.toFixed(1)}%">
      <span class="risk-dot"></span>
      <span class="risk-marker-label">${escapeHtml(r.at_time)}</span>
    </div>`;
  });
  html += `</div>`;

  // --- 逐項卡片 ---
  html += `<div class="risk-list">`;
  risks.forEach(r => {
    const cls = _RISK_LEVEL_CLASS[r.level] || "";
    const delta = (r.projected_saturation - r.baseline_saturation).toFixed(2);
    html += `<div class="risk-item ${cls}">
      <div class="risk-item-head">
        <span class="risk-when">${escapeHtml(r.at_time)}</span>
        <span class="risk-in">事故後 ${escapeHtml(String(r.at_minutes))} 分</span>
        <span class="risk-level-chip">${escapeHtml(r.level)} 級</span>
      </div>
      <div class="risk-what">
        <strong>${escapeHtml(r.segment_name)}</strong> 飽和度
        <span class="risk-from">${escapeHtml(String(r.baseline_saturation))}</span>
        <span class="risk-arrow">▸</span>
        <span class="risk-to">${escapeHtml(String(r.projected_saturation))}</span>
        <span class="risk-delta">+${escapeHtml(delta)}</span>
        <span class="risk-threshold">門檻 ${escapeHtml(String(r.threshold))}</span>
      </div>
      <div class="risk-cause">${escapeHtml(r.cause)}</div>
      <div class="risk-mitigation">
        <span class="risk-clause">${escapeHtml(r.clause_id)}</span>
        ${escapeHtml(r.mitigation)}
      </div>
    </div>`;
  });
  html += `</div>`;

  html += _renderAssumptions(projection);
  html += `</div>`;
  return html;
}

/**
 * 推演假設一律攤開。
 *
 * 這是推估不是觀測，讀的人有權知道它建立在什麼之上、可以質疑哪一條。
 * 藏起來的模型參數等於要求對方無條件相信，那在指揮決策場景是不能接受的。
 */
function _renderAssumptions(projection) {
  const items = projection.assumptions || [];
  if (items.length === 0) return "";
  return `<details class="risk-assumptions">
    <summary>推演假設與模型參數</summary>
    <ul>${items.map(a => `<li>${escapeHtml(a)}</li>`).join("")}</ul>
  </details>`;
}
