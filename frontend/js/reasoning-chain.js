/**
 * What-if 推理鏈視覺化。
 *
 * 取代的東西
 * ----------
 * [2026-08-01] 原本 What-if 卡片把後端的 `judgment_basis`（一份多行 Markdown
 * 字串）直接 `escapeHtml` 塞進一個 0.8rem 的灰字 div——換行與粗體全被吃掉，
 * 畫面上是一坨沒有斷點的文字。而「查看推理過程」展開後只有 SOP 條文原文，
 * 看不到真正的推理：假設了什麼、哪些數值變了、所以命中哪些條款、路線怎麼改。
 *
 * 這支檔案改讀後端的 `judgment_steps`（結構化）與 `current_data`（含改前值），
 * 畫成一條由上而下的推論鏈：
 *
 *     假設條件  →  命中條款  →  路線規劃  →  恢復時間
 *
 * 設計原則
 * --------
 * - **數字用圖形表達比較**：門檻用比例條、改前改後用箭頭與增減量。單獨一個
 *   「0.98」沒有資訊量，「0.78 ▶ 0.98（門檻 0.95）」才看得出為什麼會觸發。
 * - **不引入任何函式庫**：純 DOM 字串與 CSS，跟專案其餘部分一致
 *   （00-tech-stack.md §2 禁止前端建置工具鏈）。
 * - **全部欄位都可能缺**：Agent 沒呼叫 simulate_scenario 時 `judgment_steps`
 *   是空陣列，此時整個區塊不渲染，不留空殼。
 */

/** 比例條最多畫到門檻的幾倍（超過就滿格，避免極端值把版面撐爆）。 */
const _RATIO_CAP = 1.6;

function _fmtNum(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return v.toLocaleString();
  return v.toFixed(2).replace(/\.?0+$/, "");
}

/** 改前改後的差值標籤。回 null 代表沒有可比較的數值。 */
function _deltaLabel(before, after) {
  if (typeof before !== "number" || typeof after !== "number") return null;
  const diff = after - before;
  if (Math.abs(diff) < 1e-9) return null;
  const sign = diff > 0 ? "+" : "";
  return { text: `${sign}${_fmtNum(diff)}`, direction: diff > 0 ? "up" : "down" };
}

/**
 * 第一段：假設條件（改了什麼、從多少變多少）。
 * 資料來自 `current_data.applied_overrides` + `current_data.entities[*].before`。
 */
function _renderAssumptionsStage(currentData) {
  if (!currentData || !currentData.applied_overrides) return "";
  const overrides = currentData.applied_overrides;
  const keys = Object.keys(overrides);
  if (keys.length === 0) return "";

  const entities = currentData.entities || {};
  let rows = "";

  keys.forEach(key => {
    const [entityId, field] = key.split(".");
    const entity = entities[entityId] || {};
    const name = entity.road_name || entity.station_name || entityId;
    const after = overrides[key];
    const before = entity.before ? entity.before[field] : undefined;
    const delta = _deltaLabel(before, after);

    rows += `<div class="rc-assumption">
      <div class="rc-assumption-target">${escapeHtml(name)}
        <span class="rc-field">${escapeHtml(field)}</span>
      </div>
      <div class="rc-assumption-values">
        ${before !== undefined
          ? `<span class="rc-before">${escapeHtml(_fmtNum(before))}</span><span class="rc-arrow">▶</span>`
          : ""}
        <span class="rc-after">${escapeHtml(_fmtNum(after))}</span>
        ${delta ? `<span class="rc-delta rc-${delta.direction}">${escapeHtml(delta.text)}</span>` : ""}
      </div>
    </div>`;
  });

  return _stageBlock("假設條件", rows, "assumptions");
}

/** 單一命中條款：畫一根「實際值 vs 門檻」的比例條。 */
function _renderRuleItem(item) {
  const hasBar = typeof item.ratio === "number";
  // 門檻線固定畫在 1/_RATIO_CAP 的位置，實際值的長度依 ratio 換算
  const thresholdPct = (1 / _RATIO_CAP) * 100;
  const valuePct = Math.min(item.ratio || 0, _RATIO_CAP) / _RATIO_CAP * 100;
  const over = hasBar && item.ratio >= 1;

  // [2026-08-01] 顯示關係分類（主因／事故路段連帶／全市背景）。
  // `evaluate_rules()` 掃的是全市，所以「命中 9 條」是「此刻全市有 9 個地方
  // 跨過門檻」，不是「這起事故引發了 9 個問題」。不標出來的話，城市另一頭
  // 的無關壅塞會被誤讀成這起事故的後果。
  const relCls = {
    assumed: "rc-rel-assumed",
    primary: "rc-rel-primary",
    related: "rc-rel-related",
    background: "rc-rel-bg",
  };
  const relBadge = item.relation_label
    ? `<span class="rc-rel ${relCls[item.relation] || ""}">${escapeHtml(item.relation_label)}</span>`
    : (item.is_primary ? `<span class="rc-rel rc-rel-primary">主因</span>` : "");

  return `<div class="rc-rule${item.is_primary ? " rc-rule-primary" : ""}">
    <div class="rc-rule-head">
      <span class="rc-clause">${escapeHtml(item.clause_id || "")}</span>
      <span class="rc-target">${escapeHtml(item.target_name || item.target || "")}</span>
      ${relBadge}
    </div>
    <div class="rc-rule-meta">
      ${escapeHtml(item.field_label || item.field || "")}
      <strong>${escapeHtml(item.value_label != null ? item.value_label : _fmtNum(item.value))}</strong>
      ${(item.threshold_label != null || (item.threshold !== null && item.threshold !== undefined))
        ? `<span class="rc-threshold">門檻 ${escapeHtml(item.threshold_label != null ? item.threshold_label : _fmtNum(item.threshold))}</span>`
        : ""}
    </div>
    ${hasBar ? `<div class="rc-bar">
      <div class="rc-bar-fill${over ? " over" : ""}" style="width:${valuePct.toFixed(1)}%"></div>
      <div class="rc-bar-threshold" style="left:${thresholdPct.toFixed(1)}%"></div>
    </div>` : ""}
  </div>`;
}

/**
 * 第二段：適用條款。
 *
 * [2026-08-01 定案：不再有「命中條款」]
 * ------------------------------------
 * 這一段原本叫「命中條款」，把規則引擎掃全市的結果（9~17 條）全部列出來。
 * 使用者連續三輪反映看不懂、覺得沒用，最後要求砍掉。他是對的：
 *
 *   `evaluate_rules()` 掃全市是為了 **Dashboard 的態勢掌握**而設計的——
 *   值班人員需要知道現在全市哪裡在燒，F1 KPI 的應變等級就是從那裡算的。
 *   那個需求成立，但它的位置在 Dashboard，不在問答。
 *
 *   它會出現在這裡，只是因為 What-if 重用了 `evaluate_rules()`，順手把
 *   `rule_hits` 一起帶了出來。對「如果仁愛路坍塌會怎樣」這個問題，
 *   全市另外 14 個地方超標從來沒幫任何人做過決定——它只是把真正重要的
 *   那一兩條擠到看不見的地方。
 *
 * 現在後端只送「適用條款」（決定處置鏈的主因 + 使用者假設的對象，通常 1~3 條），
 * 前端就照著畫，不再有摺疊、不再有「共 N 條」。
 */
function _renderRulesStage(step) {
  const extra = step.extra || {};
  const items = step.items || [];

  const level = extra.traffic_level;
  const levelChip = level && level !== "normal"
    ? `<span class="rc-level rc-level-${escapeHtml(level)}">${escapeHtml(level)} 級</span>`
    : `<span class="rc-level rc-level-normal">正常</span>`;

  let head = "";

  // 評估時刻一定要講：同一條路在 22:10 與 23:30 是完全不同的世界
  // （實測市民大道四段 0.78 vs 0.98）。少了它，下面每個數字都無從追問。
  if (extra.as_of) {
    const reason = extra.as_of_reason ? `・${extra.as_of_reason}` : "";
    head += `<span class="rc-composition-time">評估時刻 ${escapeHtml(extra.as_of)}${escapeHtml(reason)}</span>`;
  }

  // 假設的對象一條規則都沒觸發時要明說，否則這一段會是空的，
  // 看起來像系統沒反應。
  const noHit = extra.assumed_no_hit || [];
  if (noHit.length) {
    head += `<span class="rc-composition-nohit">你假設的 ${escapeHtml(noHit.join("、"))}
      在此時刻未跨過任何條款門檻</span>`;
  }

  let rows = head ? `<div class="rc-composition">${head}</div>` : "";

  rows += items.length
    ? items.map(_renderRuleItem).join("")
    : `<div class="rc-empty">此情境未觸發任何 SOP 條款門檻</div>`;

  return _stageBlock(`適用條款 ${levelChip}`, rows, "rules", true);
}

/** 第三段：路線規劃 — 主/次/排除各自著色。 */
function _renderRoutesStage(step) {
  const extra = step.extra || {};

  // [2026-08-01] 原本這裡遇到 no_feasible_route 就 `return` 一句「無可行替代路線」，
  // 把所有候選路線與**排除理由全部藏掉**。使用者只看到一個結論，看不到
  // 「為什麼全部被排除」——而那正是他唯一需要知道的事（是容量不足？不相鄰？
  // 還是已經飽和？三種對應完全不同的處置）。
  //
  // 現在不再提早 return：標題標明無合格路線，下面照樣列出每個候選被排除的原因。
  //
  // 另外把兩個容易混淆的概念在措辭上拆開：
  //   no_feasible_route（本階段）= **現在就**找不到合格路線
  //   no_safe_route（風險推演）   = 現在有路，但推演後都會飽和
  // 兩者操作意義完全不同，之前都顯示成「無可行替代路線」，分不出來。
  //   all_alternatives_saturated（[2026-08-02] 第三種）= 有指派，但指派的本身就是塞的
  const noRouteBanner = extra.no_feasible_route
    ? `<div class="rc-no-route">目前無合格替代路線　—　以下為各候選被排除的原因</div>`
    : extra.all_alternatives_saturated
    ? `<div class="rc-no-route">目前無路段可以替補　—　候選全數飽和，下列主/次線為權宜指派</div>`
    : "";

  const roleMeta = {
    primary: ["主線", "rc-route-primary"],
    secondary: ["次線", "rc-route-secondary"],
    excluded: ["排除", "rc-route-excluded"],
  };

  let rows = "";
  (step.items || []).forEach(item => {
    const [label, cls] = roleMeta[item.role] || ["候選", ""];
    const detail = item.role === "excluded"
      ? escapeHtml(item.reason || "")
      : [
          item.saturation_score !== null && item.saturation_score !== undefined
            ? `飽和度 ${_fmtNum(item.saturation_score)}` : "",
          item.capacity_vph ? `容量 ${_fmtNum(item.capacity_vph)}` : "",
        ].filter(Boolean).map(escapeHtml).join(" · ");

    rows += `<div class="rc-route ${cls}">
      <span class="rc-route-role">${escapeHtml(label)}</span>
      <span class="rc-route-name">${escapeHtml(item.name || item.segment_id || "")}</span>
      <span class="rc-route-detail">${detail}</span>
    </div>`;
  });

  if (!rows) {
    rows = `<div class="rc-empty">此情境未產生路網重規劃</div>`;
  }

  return _stageBlock("路線規劃", noRouteBanner + rows, "routes");
}

/** 第四段：恢復時間 — 把公式拆出來，讓數字可追溯。 */
function _renderEteStage(step) {
  const e = step.extra || {};
  const rows = `<div class="rc-ete">
    <div class="rc-ete-value">${escapeHtml(_fmtNum(e.minutes))}<span>分鐘</span></div>
    <div class="rc-ete-side">
      ${e.recovery_at ? `<div>預計恢復 <strong>${escapeHtml(e.recovery_at)}</strong></div>` : ""}
      ${e.formula ? `<div class="rc-formula">${escapeHtml(e.formula)}</div>` : ""}
    </div>
  </div>`;
  return _stageBlock("恢復時間", rows, "ete");
}

/** 共用的階段外框（左側縱線 + 標題 + 內容）。 */
function _stageBlock(title, innerHtml, stage, titleIsHtml) {
  if (!innerHtml) return "";
  return `<div class="rc-stage rc-stage-${stage}">
    <div class="rc-stage-title">${titleIsHtml ? title : escapeHtml(title)}</div>
    <div class="rc-stage-body">${innerHtml}</div>
  </div>`;
}

/** 跟正式決策的差異 — 只有方案B（情境建議書）會有值。 */
function _renderDifferences(differences) {
  if (!differences || differences.length === 0) return "";
  const fieldLabels = {
    "traffic_level": "應變等級",
    "ete.minutes": "恢復時間",
    "routes": "推薦路線",
    "triggered_sop_clauses": "觸發條款",
  };
  let rows = "";
  differences.forEach(d => {
    const fmt = v => {
      if (v === null || v === undefined) return "—";
      if (Array.isArray(v)) return v.join("、");
      if (typeof v === "object") return Object.values(v).filter(Boolean).join("、") || "—";
      return String(v);
    };
    rows += `<div class="rc-diff">
      <span class="rc-diff-field">${escapeHtml(fieldLabels[d.field] || d.field)}</span>
      <span class="rc-before">${escapeHtml(fmt(d.base_value))}</span>
      <span class="rc-arrow">▶</span>
      <span class="rc-after">${escapeHtml(fmt(d.new_value))}</span>
    </div>`;
  });
  return _stageBlock("與正式決策的差異", rows, "diff");
}

/**
 * [2026-08-02 已移除：renderDecisionTrace()]
 * ------------------------------------------
 * 這裡原本有一支把後端 `trace_steps` 畫成時間軸的函式（誰在第幾步呼叫了什麼
 * 工具、依據哪條 SOP、耗時幾毫秒）。整段連同 `.decision-trace / .tr-*` 樣式
 * 一併拿掉，理由記在 `chat-render.js::renderAIResponse()`：
 *
 *   軌跡是稽核資料，放在幾百像素寬的側邊對話框裡，會把真正的答案往下擠掉
 *   一整屏。決策的「為什麼」在 Report 頁的「決策推理過程」講得完整得多
 *   （`decision-reasoning.js`），那裡有版面也有對照的原始依據。
 *
 * 後端 `decision_trace` 模組本身沒有動——M4B 生成層與 `/api/trace/{id}`
 * 還在用，只是不再流進對話框。
 */

/**
 * 主入口：把整條推理鏈畫出來。
 * 沒有任何可畫的資料時回空字串（呼叫端據此決定要不要顯示外框）。
 */
function renderReasoningChain(data) {
  const steps = data.judgment_steps || [];
  const hasDiff = data.differences_from_base && data.differences_from_base.length > 0;
  if (steps.length === 0 && !hasDiff) return "";

  let html = `<div class="reasoning-chain">`;
  html += _renderAssumptionsStage(data.current_data);

  steps.forEach(step => {
    if (step.stage === "rules") html += _renderRulesStage(step);
    else if (step.stage === "routes") html += _renderRoutesStage(step);
    else if (step.stage === "ete") html += _renderEteStage(step);
  });

  html += _renderDifferences(data.differences_from_base);
  html += `</div>`;
  return html;
}
