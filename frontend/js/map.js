/**
 * F4 SVG 拓樸圖：依 display_geometry.json 定位，依 DecisionResult.routes 上色。
 * 色彩規則（02-data-contract.md §8）：
 *   主路線亮綠實線、次路線黃色虛線、封閉路段紅色粗線、正常青綠。
 * 不用 Leaflet/Mapbox（00-tech-stack.md 禁用），用原生 SVG。
 */

let mapGeometry = null;

async function initMap() {
  const container = document.getElementById("f4-map");
  if (!container) return;

  try {
    const resp = await fetch("/frontend/data/display_geometry.json");
    if (!resp.ok) {
      // 嘗試從根路徑
      const resp2 = await fetch("/data/display_geometry.json");
      if (resp2.ok) mapGeometry = await resp2.json();
    } else {
      mapGeometry = await resp.json();
    }
  } catch (e) {
    // 靜態載入失敗，用內嵌 fallback
    mapGeometry = null;
  }

  renderMap(container);
}

function renderMap(container, routes) {
  if (!mapGeometry) {
    container.innerHTML = `<div style="color:#64748b;text-align:center;padding:40px">路網拓樸圖載入中...</div>`;
    return;
  }

  const vb = mapGeometry.viewBox || "0 0 800 600";
  const points = mapGeometry.display_points || [];

  let svg = `<svg viewBox="${vb}" style="width:100%;height:100%;" xmlns="http://www.w3.org/2000/svg">`;

  // 背景
  svg += `<rect width="800" height="600" fill="#0f172a" rx="8"/>`;

  // 繪製路段節點
  points.forEach((p) => {
    const color = getSegmentColor(p.segment_id, routes);
    const strokeWidth = getSegmentStroke(p.segment_id, routes);
    const dashArray = getSegmentDash(p.segment_id, routes);

    svg += `<circle cx="${p.x}" cy="${p.y}" r="8" fill="${color}" stroke="${color}" stroke-width="${strokeWidth}" stroke-dasharray="${dashArray}" opacity="0.9"/>`;
    // 標籤
    const label = (p.$note || p.segment_id).replace(/，.*/, "");
    svg += `<text x="${p.x}" y="${p.y + 20}" text-anchor="middle" fill="#94a3b8" font-size="9">${escapeHtml(label)}</text>`;
  });

  svg += `</svg>`;
  container.innerHTML = svg;
}

function getSegmentColor(segId, routes) {
  if (!routes) return "#06b6d4"; // 正常青綠
  if (routes.primary && routes.primary.segment_id === segId) return "#22c55e"; // 主路線亮綠
  if (routes.secondary && routes.secondary.segment_id === segId) return "#eab308"; // 次路線黃
  const excluded = routes.excluded || [];
  if (excluded.some((e) => e.segment_id === segId && e.reason_code === "CLOSED")) return "#dc2626"; // 封閉紅
  if (excluded.some((e) => e.segment_id === segId)) return "#64748b"; // 排除灰
  return "#06b6d4";
}

function getSegmentStroke(segId, routes) {
  if (!routes) return "2";
  if (routes.primary && routes.primary.segment_id === segId) return "3";
  const excluded = routes.excluded || [];
  if (excluded.some((e) => e.segment_id === segId && e.reason_code === "CLOSED")) return "3";
  return "2";
}

function getSegmentDash(segId, routes) {
  if (!routes) return "none";
  if (routes.secondary && routes.secondary.segment_id === segId) return "4,3"; // 虛線
  return "none";
}

function updateMap(routes) {
  const container = document.getElementById("f4-map");
  if (container) renderMap(container, routes);
}
