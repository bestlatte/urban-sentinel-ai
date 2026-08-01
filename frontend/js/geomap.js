/**
 * F4-B 路網關係圖 — 手繪 SVG 佈局，暖棕色系統一。
 */

const SEG_IDS = {
  "RD_TPE_004": "road-004",
  "RD_TPE_001": "road-001",
  "RD_TPE_005": "road-005",
  "RD_TPE_007": "road-007",
  "RD_TPE_011": "road-011",
  "RD_TPE_013": "road-013",
  "RD_TPE_015": "road-015",
  "RD_TPE_006": "road-006",
  "RD_TPE_008": "road-008",
  "RD_TPE_002": "road-002",
  "RD_TPE_003": "road-003",
  "RD_TPE_010": "road-010",
  "RD_TPE_014": "road-014",
  "RD_TPE_012": "road-012",
  "RD_TPE_009": "road-009",
};

const DEFAULT_COLOR = "#b0b0b0";
const DEFAULT_WIDTH = 10;

const GEO_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 60 1780 920" style="width:100%;height:100%">
  <rect x="0" y="60" width="1780" height="920" fill="#F3E8D7" rx="8"/>

  <!-- 横向主要道路 -->
  <path id="road-004" d="M 340 295 L 535 295 L 740 310 L 910 295" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  <line id="road-001" x1="320" y1="390" x2="1170" y2="390" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <line id="road-005" x1="325" y1="480" x2="1100" y2="485" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <line id="road-007" x1="1065" y1="440" x2="1465" y2="445" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <line id="road-011" x1="1040" y1="525" x2="1320" y2="525" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <path id="road-013" d="M 970 600 L 1120 600 L 1510 605 L 1590 580" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>

  <!-- 縱向與斜向道路 -->
  <line id="road-015" x1="345" y1="225" x2="330" y2="600" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <line id="road-006" x1="535" y1="205" x2="535" y2="925" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <line id="road-012" x1="535" y1="600" x2="535" y2="925" fill="none" stroke="#b0b0b0" stroke-width="7" stroke-linecap="round"/>
  <path id="road-008" d="M 730 210 L 750 317 L 800 480 L 840 545 L 905 585" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  <line id="road-002" x1="910" y1="200" x2="900" y2="705" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <line id="road-003" x1="1440" y1="120" x2="970" y2="600" fill="none" stroke="#b0b0b0" stroke-width="11" stroke-linecap="round"/>
  <line id="road-010" x1="1120" y1="485" x2="1125" y2="600" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round"/>
  <path id="road-014" d="M 1220 442 L 1222 600 L 1200 660 L 1230 685" fill="none" stroke="#b0b0b0" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  <line id="road-009" x1="970" y1="600" x2="900" y2="705" fill="none" stroke="#b0b0b0" stroke-width="7" stroke-linecap="round" stroke-dasharray="12,7"/>

  <!-- 節點：藍色空心圓（白色填充確保在路段上方可見） -->
  <g id="geo-nodes">
  <circle cx="345" cy="295" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="535" cy="295" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="740" cy="310" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="908" cy="295" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="338" cy="390" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="535" cy="390" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="767" cy="390" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="905" cy="390" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1170" cy="390" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="335" cy="480" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="535" cy="480" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="800" cy="480" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="903" cy="483" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1120" cy="441" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1220" cy="442" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1075" cy="484" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1120" cy="485" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1045" cy="525" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1122" cy="525" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1221" cy="525" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="535" cy="600" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="901" cy="585" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="970" cy="600" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1125" cy="600" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  <circle cx="1222" cy="600" r="8" fill="#F3E8D7" stroke="#4a90d9" stroke-width="2.5"/>
  </g>

  <!-- 文字標籤 -->
  <text x="140" y="300" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">市民大道四段</text>
  <text x="140" y="395" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">忠孝東路四段</text>
  <text x="140" y="488" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">仁愛路四段</text>
  <text x="1475" y="440" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">松高路</text>
  <text x="1330" y="522" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">松壽路</text>
  <text x="1600" y="580" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">信義路五段</text>
  <text x="140" y="640" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">復興南路一段</text>
  <text x="495" y="188" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">敦化南路一段</text>
  <text x="495" y="870" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">敦化南路二段</text>
  <text x="710" y="195" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">延吉街</text>
  <text x="870" y="185" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">光復南路</text>
  <text x="1410" y="105" fill="#4a3728" font-size="30" font-weight="600" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">基隆路一段</text>
  <text x="1080" y="632" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">市府路</text>
  <text x="1170" y="718" fill="#4a3728" font-size="30" font-weight="500" font-family="-apple-system,Noto Sans TC,PingFang TC,sans-serif">松智路</text>

  <!-- 圖例 -->
  <g transform="translate(420,910)">
    <rect x="-20" y="-28" width="600" height="60" rx="8" fill="#F3E8D7" stroke="#B78E62" stroke-width="1.5"/>
    <line x1="0" y1="0" x2="40" y2="0" stroke="#f97316" stroke-width="10" stroke-linecap="round"/><text x="50" y="7" fill="#333" font-size="24" font-weight="600" font-family="-apple-system,Noto Sans TC,sans-serif">主要</text>
    <line x1="135" y1="0" x2="175" y2="0" stroke="#22c55e" stroke-width="10" stroke-linecap="round"/><text x="185" y="7" fill="#333" font-size="24" font-weight="600" font-family="-apple-system,Noto Sans TC,sans-serif">次要</text>
    <line x1="270" y1="0" x2="310" y2="0" stroke="#dc2626" stroke-width="10" stroke-linecap="round"/><text x="320" y="7" fill="#333" font-size="24" font-weight="600" font-family="-apple-system,Noto Sans TC,sans-serif">封閉</text>
    <line x1="405" y1="0" x2="445" y2="0" stroke="#c0b0a0" stroke-width="10" stroke-linecap="round" stroke-dasharray="10,14"/><text x="455" y="7" fill="#333" font-size="24" font-weight="600" font-family="-apple-system,Noto Sans TC,sans-serif">排除</text>
  </g>
</svg>`;

function initGeoMap() {
  const container = document.getElementById("f4-geomap");
  if (!container) return;
  container.innerHTML = GEO_SVG;
}

function updateGeoMap(routes) {
  if (!routes) return;

  Object.values(SEG_IDS).forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.setAttribute("stroke", DEFAULT_COLOR);
      el.setAttribute("stroke-width", String(DEFAULT_WIDTH));
      el.setAttribute("opacity", "1");
      el.removeAttribute("stroke-dasharray");
    }
  });

  const excluded = routes.excluded || [];
  excluded.forEach(e => {
    const el = document.getElementById(SEG_IDS[e.segment_id]);
    if (el) {
      if (e.reason_code === "CLOSED") {
        el.setAttribute("stroke", "#dc2626");
        el.setAttribute("stroke-width", "14");
      } else {
        el.setAttribute("stroke", "#c0b0a0");
        el.setAttribute("opacity", "0.9");
        el.setAttribute("stroke-dasharray", "10,14");
      }
    }
  });

  if (routes.secondary) {
    const el = document.getElementById(SEG_IDS[routes.secondary.segment_id]);
    if (el) { el.setAttribute("stroke", "#22c55e"); el.setAttribute("stroke-width", "14"); }
  }

  if (routes.primary) {
    const el = document.getElementById(SEG_IDS[routes.primary.segment_id]);
    if (el) { el.setAttribute("stroke", "#f97316"); el.setAttribute("stroke-width", "14"); }
  }

  // 確保節點圓圈在最上層
  const nodesGroup = document.getElementById("geo-nodes");
  if (nodesGroup && nodesGroup.parentNode) {
    nodesGroup.parentNode.appendChild(nodesGroup);
  }
}

function markIncidentOnGeoMap(incident) {
  if (!incident || !incident.affected_segment) return;
  const el = document.getElementById(SEG_IDS[incident.affected_segment]);
  if (el) {
    el.setAttribute("stroke", "#dc2626");
    el.setAttribute("stroke-width", "14");
  }
  // 確保節點圓圈在最上層
  const nodesGroup = document.getElementById("geo-nodes");
  if (nodesGroup && nodesGroup.parentNode) {
    nodesGroup.parentNode.appendChild(nodesGroup);
  }
}
