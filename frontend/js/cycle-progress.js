/**
 * 決策週期進度條：LLM 生成階段的等待回饋。
 *
 * 為什麼需要這個
 * --------------
 * 注入事件後，建議書生成要跑 15~20 秒的 Bedrock 呼叫。在此之前這段時間畫面上
 * 沒有任何訊息，使用者看到的就是「系統當掉了」。
 *
 * [2026-08-01 第二版：修掉第一版的兩個實際問題]
 * ---------------------------------------------
 * **問題一：倒數會提前歸零，然後報告還沒出來。**
 * 第一版顯示的是「約 N 秒」倒數，數字來自後端的 `eta_seconds`（20 秒，取自實測
 * 平均）。但那是**估計值**，LLM 實際耗時本來就會浮動——只要超過估計，倒數就會
 * 停在「即將完成」而畫面什麼都沒發生。倒數歸零卻沒有結果，比沒有倒數更像壞掉：
 * 它給了一個系統無法兌現的承諾。
 *
 * 改成顯示**已等待秒數**（往上數）。已等待是事實，不是預測，永遠不會失準。
 * 超過估計值之後，進度條轉成不定量的來回動畫，明確表達「還在跑，但不知道還要
 * 多久」——這也是事實。
 *
 * **問題二：動一下 dashboard 其他 UI，進度條就不見了。**
 * 第一版的收掉條件是「任何 status 以 `_done` 結尾」。在報告生成中按「生成事件」
 * 會開一個新的決策週期，新週期的 `routing_done`（毫秒級就完成）立刻把**上一個
 * 週期**的進度條殺掉。加上 z-index 900 低於 modal 的 1000，彈窗一出來也會蓋住。
 *
 * 改成用 `trace_id` + 階段名配對：只有「我這一格對應的那個 done」才收掉，別的
 * 週期的訊息一律忽略。z-index 提到 modal 之上（進度條是狀態列不是內容，被蓋住
 * 就失去意義）。並且每次 tick 檢查元素還在不在，被移除就重新掛回去。
 */

const CycleProgress = {
  _timer: null,
  _startedAt: 0,
  _etaMs: 0,
  _el: null,
  _traceId: null,
  _stage: null,
  _label: "",
  _indeterminate: false,
};

/** 估計時間內，進度條最多推進到這個比例；剩下的留給實際完成訊號。 */
const _PROGRESS_CEILING = 0.9;

/** 超過估計值多少倍就自己收掉（防止後端漏送 done 時卡在畫面上）。 */
const _WATCHDOG_FACTOR = 6;

/** 從 `report_started` / `explain_done` 取出階段名（`report` / `explain`）。 */
function _stageOf(status) {
  if (typeof status !== "string") return null;
  const idx = status.lastIndexOf("_");
  return idx > 0 ? status.slice(0, idx) : status;
}

function _ensureProgressEl() {
  // 每次都檢查元素還在不在——第一版把它快取起來就不管了，一旦被任何
  // re-render 移除就再也回不來。
  if (CycleProgress._el && document.body.contains(CycleProgress._el)) {
    return CycleProgress._el;
  }
  const el = document.createElement("div");
  el.id = "cycle-progress";
  el.className = "cycle-progress";
  el.innerHTML = `
    <div class="cycle-progress-row">
      <span class="cycle-progress-spinner"></span>
      <span class="cycle-progress-label" id="cycle-progress-label"></span>
      <span class="cycle-progress-eta" id="cycle-progress-eta"></span>
    </div>
    <div class="cycle-progress-track"><div class="cycle-progress-fill" id="cycle-progress-fill"></div></div>
  `;
  document.body.appendChild(el);
  CycleProgress._el = el;
  return el;
}

/**
 * 開始顯示進度條。
 * @param {object} payload `decision.task_update.v1` 的 payload
 */
function showCycleProgress(payload) {
  const el = _ensureProgressEl();
  const eta = Math.max(1, Number(payload.eta_seconds) || 15);

  CycleProgress._startedAt = Date.now();
  CycleProgress._etaMs = eta * 1000;
  CycleProgress._traceId = payload.trace_id || null;
  CycleProgress._stage = _stageOf(payload.status);
  CycleProgress._label = payload.label || "處理中";
  CycleProgress._indeterminate = false;

  el.classList.add("visible");
  el.classList.remove("indeterminate");

  if (CycleProgress._timer) clearInterval(CycleProgress._timer);
  CycleProgress._timer = setInterval(_tickProgress, 200);
  _tickProgress();
}

function _tickProgress() {
  const el = _ensureProgressEl();
  const elapsed = Date.now() - CycleProgress._startedAt;
  const seconds = Math.floor(elapsed / 1000);

  const labelEl = document.getElementById("cycle-progress-label");
  const etaEl = document.getElementById("cycle-progress-eta");
  const fill = document.getElementById("cycle-progress-fill");

  if (elapsed < CycleProgress._etaMs) {
    // 估計時間內：依 easeOut 推進。前段快讓人立刻看到它在動，後段自然放慢。
    const ratio = elapsed / CycleProgress._etaMs;
    const eased = (1 - Math.pow(1 - ratio, 2)) * _PROGRESS_CEILING;
    if (fill) fill.style.width = `${(eased * 100).toFixed(1)}%`;
    if (labelEl) labelEl.textContent = CycleProgress._label;
  } else {
    // 超過估計：不再假裝知道進度。條子轉成來回跑的不定量動畫，文字說實話。
    if (!CycleProgress._indeterminate) {
      CycleProgress._indeterminate = true;
      el.classList.add("indeterminate");
      if (fill) fill.style.width = "";
    }
    if (labelEl) labelEl.textContent = `${CycleProgress._label}（仍在生成）`;
  }

  // 已等待秒數是**事實**，不是預測，所以永遠不會失準——這是第一版倒數的問題所在。
  if (etaEl) etaEl.textContent = `已等待 ${seconds} 秒`;

  if (elapsed > CycleProgress._etaMs * _WATCHDOG_FACTOR) {
    hideCycleProgress();
  }
}

/** 收掉進度條。先補滿到 100% 再淡出，避免視覺上「還沒跑完就消失」。 */
function hideCycleProgress() {
  if (CycleProgress._timer) {
    clearInterval(CycleProgress._timer);
    CycleProgress._timer = null;
  }
  CycleProgress._traceId = null;
  CycleProgress._stage = null;

  const el = CycleProgress._el;
  if (!el) return;

  el.classList.remove("indeterminate");
  const fill = document.getElementById("cycle-progress-fill");
  if (fill) fill.style.width = "100%";

  setTimeout(() => el.classList.remove("visible"), 250);
}

/**
 * `decision.task_update.v1` 的進度條分派。
 *
 * 只有帶 `eta_seconds` 的階段會開進度條（建議書生成、決策說明）；毫秒級的
 * 確定性運算不畫——為了 200ms 的路網規劃閃一條進度條只是視覺雜訊。
 *
 * 收掉的條件是**配對**而不是「任何 done」：必須 trace_id 與階段名都對得上。
 * 這是第一版「動一下 dashboard 進度條就不見」的成因——同時跑第二個決策週期時，
 * 新週期毫秒級完成的 routing_done 會誤殺舊週期的進度條。
 */
function onTaskUpdateProgress(payload) {
  if (!payload || !payload.status) return;

  if (payload.eta_seconds) {
    showCycleProgress(payload);
    return;
  }

  if (!CycleProgress._stage) return; // 目前沒有顯示中的進度條

  const stage = _stageOf(payload.status);
  const isDone = typeof payload.status === "string" && payload.status.endsWith("_done");
  if (!isDone || stage !== CycleProgress._stage) return;

  // trace_id 也要對得上。後端沒帶 trace_id 時（理論上不會）就只比階段名，
  // 總比完全不收掉好。
  if (CycleProgress._traceId && payload.trace_id && payload.trace_id !== CycleProgress._traceId) {
    return;
  }

  hideCycleProgress();
}
