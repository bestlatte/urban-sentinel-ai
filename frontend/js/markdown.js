/**
 * 極簡 Markdown 渲染器（純原生 JS，零依賴）。
 *
 * 為什麼自己寫
 * -----------
 * `00-tech-stack.md` §2 禁止 React 建置工具鏈，前端是純原生 JS + 少數 vendor
 * 檔案。引一整包 marked.js 只為了渲染四種語法不划算，而且 LLM 的輸出語法範圍
 * 已經被 prompts/report.txt 與 prompts/advisor.txt 限縮過。
 *
 * 為什麼需要它
 * -----------
 * C1-C3 建議書與 What-if 對話的回覆**本來就是 Markdown**，但前端三個地方
 * （app.js 的報告面板與彈窗、chat-render.js 的對話氣泡）都是
 * `escapeHtml(text)` 直接輸出，於是 `**粗體**`、`## 標題`、`| 表格 |`
 * 全部以原始字元顯示。使用者看到的「排版很像 markdown」就是這個原因——
 * 它不是「像」，它就是沒被渲染的 Markdown。
 *
 * 安全性
 * ------
 * **先逃逸、再套用語法**，順序不可對調。所有輸入在第一步就被
 * `escapeHtml()` 轉成純文字，之後只會由本檔案自己插入白名單標籤
 * （h2/h3/strong/em/code/ul/ol/li/table/tr/th/td/blockquote/hr/p/br）。
 * 因此即使 LLM 回覆裡含 `<script>` 或 `onerror=`，也只會被當成文字顯示，
 * 不可能執行——這點很重要，因為回覆內容部分來自使用者的提問。
 *
 * 支援語法（刻意只有這些）
 * ------------------------
 *   ## 標題 / ### 標題
 *   **粗體**  *斜體*  `行內程式碼`
 *   - 項目 / * 項目 / 1. 項目
 *   > 引言
 *   ---（水平線）
 *   | 表格 | 標頭 |
 *
 * 不支援：圖片、連結、巢狀清單、程式碼區塊、HTML 內嵌。這些在指揮中心的
 * 建議書裡沒有用途，支援它們只是擴大攻擊面。
 */

(function (global) {
  "use strict";

  /** 與 chat-utils.js 的 escapeHtml 同義。這裡自己寫一份是為了讓本檔案可以
   *  獨立載入，不依賴 script 標籤的順序（app.js 也會用到它）。 */
  function esc(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
  }

  /** 行內語法。輸入必須是**已經逃逸過**的字串。 */
  function inline(s) {
    return s
      // `code`
      .replace(/`([^`\n]+)`/g, '<code class="md-code">$1</code>')
      // **bold**
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      // *italic*（放在粗體之後，避免把 ** 拆成兩個 *）
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>");
  }

  /** 一行是不是表格分隔列（|---|:--:|）。 */
  function isTableDivider(line) {
    return /^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$/.test(line) && line.includes("-");
  }

  function splitRow(line) {
    return line
      .replace(/^\s*\|/, "")
      .replace(/\|\s*$/, "")
      .split("|")
      .map((c) => c.trim());
  }

  /**
   * Markdown → 安全 HTML。
   * @param {string} text 原始 Markdown（未逃逸）
   * @returns {string} 可直接塞進 innerHTML 的 HTML
   */
  function render(text) {
    if (text == null || text === "") return "";

    // ① 先逃逸。這一步之後，字串裡不可能再有活的 HTML。
    const lines = esc(String(text)).split(/\r?\n/);

    const out = [];
    let listType = null; // "ul" | "ol" | null
    let paragraph = [];

    function closeList() {
      if (listType) {
        out.push(`</${listType}>`);
        listType = null;
      }
    }

    function closeParagraph() {
      if (paragraph.length) {
        out.push(`<p>${inline(paragraph.join("<br>"))}</p>`);
        paragraph = [];
      }
    }

    function closeAll() {
      closeParagraph();
      closeList();
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      // 空行 → 段落分隔
      if (trimmed === "") {
        closeAll();
        continue;
      }

      // 水平線
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        closeAll();
        out.push('<hr class="md-hr">');
        continue;
      }

      // 標題。#### 以下一律降成 h4，不讓 LLM 的層級失控影響版面。
      const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        closeAll();
        const level = Math.min(heading[1].length + 1, 4); // # → h2
        out.push(`<h${level} class="md-h">${inline(heading[2])}</h${level}>`);
        continue;
      }

      // 表格：本行含 | 且下一行是分隔列
      if (trimmed.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
        closeAll();
        const header = splitRow(trimmed);
        const rows = [];
        i += 2; // 跳過標頭與分隔列
        while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
          rows.push(splitRow(lines[i]));
          i++;
        }
        i--; // 外層迴圈會再 ++

        let table = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
        header.forEach((h) => (table += `<th>${inline(h)}</th>`));
        table += "</tr></thead><tbody>";
        rows.forEach((r) => {
          table += "<tr>";
          r.forEach((c) => (table += `<td>${inline(c)}</td>`));
          table += "</tr>";
        });
        table += "</tbody></table></div>";
        out.push(table);
        continue;
      }

      // 引言
      const quote = trimmed.match(/^&gt;\s?(.*)$/); // 逃逸後 ">" 變成 "&gt;"
      if (quote) {
        closeAll();
        out.push(`<blockquote class="md-quote">${inline(quote[1])}</blockquote>`);
        continue;
      }

      // 無序清單
      const ul = trimmed.match(/^[-*•]\s+(.*)$/);
      if (ul) {
        closeParagraph();
        if (listType !== "ul") {
          closeList();
          out.push('<ul class="md-list">');
          listType = "ul";
        }
        out.push(`<li>${inline(ul[1])}</li>`);
        continue;
      }

      // 有序清單
      const ol = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (ol) {
        closeParagraph();
        if (listType !== "ol") {
          closeList();
          out.push('<ol class="md-list">');
          listType = "ol";
        }
        out.push(`<li>${inline(ol[1])}</li>`);
        continue;
      }

      // 一般段落
      closeList();
      paragraph.push(trimmed);
    }

    closeAll();
    return out.join("");
  }

  global.renderMarkdown = render;
})(window);
