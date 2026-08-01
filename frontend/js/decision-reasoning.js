/**
 * 決策推理過程：step by step 交代這份建議書是怎麼推出來的。
 *
 * 為什麼要有這個
 * --------------
 * [2026-08-02] Report 頁原本只有「結果」——命中什麼、走哪條、多久恢復。
 * 指揮官看完會問的是「**為什麼**」，而每一個為什麼的答案都散在不同地方：
 * 選擇規則在 RoutePlan、排除理由在 excluded、公式在 ETE、風險在 projected_risks。
 *
 * 這支檔案把它們串成一條可讀的推理鏈，每一步都交代「依據」與「來源」。
 *
 * 跟對話框那條推理鏈（reasoning-chain.js）的差別：
 *   reasoning-chain  ← judgment_steps（What-if **重算**的結果）
 *   decision-reasoning ← DecisionResult（正式決策**實際跑**的結果）
 * 兩者資料來源不同，不能共用同一個渲染函式，但視覺語彙刻意做成一致的，
 * 使用者在兩邊看到的是同一種東西。
 */

const _DR_POSITION = { upstream: "上游", downstream: "下游", parallel: "平行替代" };

const _DR_REASON_TEXT = {
  CLOSED: "事故封閉路段",
  CAPACITY_INSUFFICIENT: "容量不足",
  NOT_IN_ALTERNATIVES: "非替代路線候選",
  NOT_DIRECTLY_INTERSECTING: "與事故路段無直接交會",
  DOWNSTREAM_ONLY: "僅位於下游",
  FLOW_DIRECTION_MISMATCH: "流向不符",
  SATURATED: "已飽和",
  UNKNOWN_SEGMENT: "未知路段",
  MISSING_TRAFFIC_SNAPSHOT: "缺少車流快照",
};

function _drStep(no, title, body, basis) {
  return `<div class="dr-step">
    <div class="dr-step-marker"><span class="dr-step-no">${no}</span></div>
    <div class="dr-step-content">
      <div class="dr-step-title">${title}</div>
      <div class="dr-step-body">${body}</div>
      ${basis ? `<div class="dr-step-basis">依據：${escapeHtml(basis)}</div>` : ""}
    </div>
  </div>`;
}

/**
 * @param {object} decision  DecisionResult
 */
function renderDecisionReasoning(decision) {
  if (!decision) return "";

  const steps = [];
  let n = 0;

  // ① 事件研判
  const inc = decision.incident;
  if (inc) {
    n += 1;
    const body = `
      <div class="dr-kv"><span>事件類型</span><strong>${escapeHtml(inc.type || "—")}</strong></div>
      <div class="dr-kv"><span>位置</span><strong>${escapeHtml(inc.location || "—")}</strong></div>
      <div class="dr-kv"><span>狀態 / 嚴重度</span><strong>${escapeHtml(inc.status || "—")} · ${escapeHtml(inc.severity || "—")}</strong></div>
      <div class="dr-kv"><span>受影響路段</span><strong>${escapeHtml(inc.affected_segment || "—")}</strong></div>`;
    steps.push(_drStep(n, "事件研判", body, "A1 事件分類器（查表，零 LLM）"));
  }

  // ② 條款判定
  if (decision.triggered_by && decision.triggered_by.length) {
    n += 1;
    const chips = decision.triggered_by
      .map(s => `<span class="dr-clause">${escapeHtml(s)}</span>`).join("");
    const level = decision.level
      ? `<div class="dr-kv"><span>研判等級</span><strong class="dr-level-${escapeHtml(decision.level)}">${escapeHtml(decision.level)} 級</strong></div>`
      : "";
    steps.push(_drStep(n, "條款判定", `<div class="dr-clauses">${chips}</div>${level}`,
      "P4 規則引擎，門檻值出自 SOP 條文"));
  }

  // ③ 路線篩選 —— 逐條交代卡在哪一關
  const routes = decision.routes;
  if (routes) {
    n += 1;
    let body = `<div class="dr-routes">`;

    [["primary", "主線"], ["secondary", "次線"]].forEach(([key, label]) => {
      const r = routes[key];
      if (!r) return;
      const pos = _DR_POSITION[r.position] || "";
      body += `<div class="dr-route dr-route-${key}">
        <span class="dr-route-label">${label}</span>
        <span class="dr-route-name">${escapeHtml(r.name || r.segment_id)}</span>
        <span class="dr-route-meta">飽和度 ${escapeHtml(String(r.saturation_score))}
          · 容量 ${escapeHtml(String(r.capacity_vph))} vph${pos ? ` · ${pos}` : ""}</span>
      </div>`;
    });

    // 每個被排除的候選都要交代卡在哪一關——這是「為什麼不是它」的答案
    (routes.excluded || []).forEach(e => {
      const why = _DR_REASON_TEXT[e.reason_code] || e.reason_code || "";
      const detail = e.capacity_vph ? `（容量 ${e.capacity_vph} vph）` : "";
      body += `<div class="dr-route dr-route-excluded">
        <span class="dr-route-label">排除</span>
        <span class="dr-route-name">${escapeHtml(e.name || e.segment_id)}</span>
        <span class="dr-route-meta">${escapeHtml(why)}${escapeHtml(detail)}</span>
      </div>`;
    });
    body += `</div>`;

    // 選擇規則：長官最常問的「為什麼是這條」，答案在這裡
    if (routes.selection_rule) {
      body += `<div class="dr-rule">${escapeHtml(routes.selection_rule)}</div>`;
    }
    if (routes.no_feasible_route) {
      body += `<div class="dr-warn">所有候選路段均被排除，無可行替代路線</div>`;
    }

    steps.push(_drStep(n, "路線篩選", body, "R1-R5 路網重規劃（純確定性，零 LLM）"));
  }

  // ④ 恢復時間
  if (decision.ete) {
    n += 1;
    const e = decision.ete;
    const body = `
      <div class="dr-ete">${escapeHtml(String(e.minutes))}<span>分鐘</span></div>
      ${e.formula ? `<div class="dr-formula">${escapeHtml(e.formula)}</div>` : ""}
      ${e.recovery_at ? `<div class="dr-kv"><span>預計恢復</span><strong>${escapeHtml(e.recovery_at)}</strong></div>` : ""}`;
    steps.push(_drStep(n, "恢復時間推算", body, "SOP-7 公式：base_clearance + 壅塞加權"));
  }

  // ⑤ 後續風險 —— 沿用同一支時間軸元件，兩處畫面必然一致
  if (typeof renderRiskTimeline === "function" && decision.projected_risks) {
    n += 1;
    steps.push(_drStep(n, "後續風險推演", renderRiskTimeline(decision.projected_risks),
      "容量轉移模型（推估，非觀測）"));
  }

  if (!steps.length) return "";

  return `<div class="decision-reasoning">
    <div class="dr-head">決策推理過程</div>
    <div class="dr-intro">以下逐步交代這份建議書是怎麼推出來的，每一步都可對照原始依據。</div>
    ${steps.join("")}
  </div>`;
}
