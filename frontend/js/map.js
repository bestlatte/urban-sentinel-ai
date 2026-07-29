/**
 * F4 SVG 拓樸圖：依 display_geometry.json 定位 + road_network_topology 連線。
 * 色彩規則（02-data-contract.md §8）：
 *   主路線亮綠、次路線黃色虛線、封閉路段紅色、正常中性灰。
 */

let mapGeometry = null;
let mapTopology = null;

async function initMap() {
  const container = document.getElementById("f4-map");
  if (!container) return;

  try {
    const [geoResp, topoResp] = await Promise.all([
      fetch("/data/display_geometry.json"),
      fetch("/data/road_network_topology.json"),
    ]);
    if (geoResp.ok) mapGeometry = await geoResp.json();
    if (topoResp.ok) mapTopology = await topoResp.json();
  } catch (e) {
    mapGeometry = null;
    mapTopology = null;
  }

  renderMap(container);
}

function renderMap(container, routes) {
  if (!mapGeometry) {
    container.innerHTML = `<div style="color:hsl(0,0%,40%);text-align:center;padding:60px 0;font-size:0.8rem">Road network loading...</div>`;
    return;
  }

  const vb = "0 0 600 500";
  const points = mapGeometry.display_points || [];
  const posMap = {};
  // 重新映射座標到更緊湊的範圍，讓節點佔滿畫布
  const rawPoints = mapGeometry.display_points || [];
  const xs = rawPoints.map(p => p.x);
  const ys = rawPoints.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const padX = 60, padY = 50;
  const scaleX = (600 - padX * 2) / (maxX - minX || 1);
  const scaleY = (500 - padY * 2) / (maxY - minY || 1);

  const mappedPoints = rawPoints.map(p => ({
    ...p,
    mx: padX + (p.x - minX) * scaleX,
    my: padY + (p.y - minY) * scaleY,
  }));
  mappedPoints.forEach((p) => { posMap[p.segment_id] = p; });

  let svg = `<svg viewBox="${vb}" style="width:100%;height:100%" xmlns="http://www.w3.org/2000/svg">`;

  // 繪製連線（alternatives 關係）
  if (mapTopology) {
    const drawnEdges = new Set();
    mapTopology.forEach((seg) => {
      const from = posMap[seg.segment_id];
      if (!from) return;
      (seg.alternatives || []).forEach((altId) => {
        const to = posMap[altId];
        if (!to) return;
        const edgeKey = [seg.segment_id, altId].sort().join("-");
        if (drawnEdges.has(edgeKey)) return;
        drawnEdges.add(edgeKey);
        const edgeColor = getEdgeColor(seg.segment_id, altId, routes);
        const edgeDash = getEdgeDash(seg.segment_id, altId, routes);
        const edgeWidth = getEdgeWidth(seg.segment_id, altId, routes);
        svg += `<line x1="${from.mx}" y1="${from.my}" x2="${to.mx}" y2="${to.my}" stroke="${edgeColor}" stroke-width="${edgeWidth}" stroke-dasharray="${edgeDash}" opacity="0.5"/>`;
      });
    });
  }

  // 繪製節點
  mappedPoints.forEach((p) => {
    const color = getSegmentColor(p.segment_id, routes);
    const r = getNodeRadius(p.segment_id, routes);
    svg += `<circle cx="${p.mx}" cy="${p.my}" r="${r}" fill="${color}" opacity="0.9"/>`;
    // 標籤
    const label = (p.$note || p.segment_id).replace(/，.*/, "").replace(/（.*）/, "");
    svg += `<text x="${p.mx}" y="${p.my + r + 14}" text-anchor="middle" fill="hsl(0,0%,50%)" font-size="11" font-family="-apple-system,sans-serif">${escapeHtml(label)}</text>`;
  });

  svg += `</svg>`;

  // 圖例
  const legend = `<div style="position:absolute;bottom:12px;right:16px;display:flex;gap:12px;font-size:0.65rem;color:hsl(0,0%,50%)">
    <span><span style="color:hsl(142,71%,45%)">●</span> 主線</span>
    <span><span style="color:hsl(48,96%,53%)">●</span> 次線</span>
    <span><span style="color:hsl(0,84%,60%)">●</span> 封閉</span>
    <span><span style="color:hsl(0,0%,30%)">●</span> 一般</span>
  </div>`;

  container.innerHTML = svg + legend;
}

function getEdgeColor(fromId, toId, routes) {
  if (!routes) return "hsl(0,0%,18%)";
  const primary = routes.primary && routes.primary.segment_id;
  const secondary = routes.secondary && routes.secondary.segment_id;
  const closedIds = (routes.excluded || []).filter(e => e.reason_code === "CLOSED").map(e => e.segment_id);

  if (closedIds.includes(fromId) || closedIds.includes(toId)) return "hsl(0,84%,60%)";
  if ((fromId === primary && toId === secondary) || (toId === primary && fromId === secondary)) return "hsl(142,71%,45%)";
  if (fromId === primary || toId === primary) return "hsl(142,71%,45%)";
  if (fromId === secondary || toId === secondary) return "hsl(48,96%,53%)";
  return "hsl(0,0%,18%)";
}

function getEdgeDash(fromId, toId, routes) {
  if (!routes) return "none";
  const secondary = routes.secondary && routes.secondary.segment_id;
  if (fromId === secondary || toId === secondary) return "4,3";
  return "none";
}

function getEdgeWidth(fromId, toId, routes) {
  if (!routes) return "1";
  const primary = routes.primary && routes.primary.segment_id;
  const closedIds = (routes.excluded || []).filter(e => e.reason_code === "CLOSED").map(e => e.segment_id);
  if (closedIds.includes(fromId) || closedIds.includes(toId)) return "2.5";
  if (fromId === primary || toId === primary) return "2";
  return "1";
}

function _isSaturatedRetained(segId, routes) {
  const findings = (routes && routes.findings) || [];
  return findings.some(
    (f) => f.finding_code === "SATURATED_BUT_RETAINED" && (f.segment_ids || []).includes(segId)
  );
}

function getSegmentColor(segId, routes) {
  if (!routes) return "hsl(0,0%,30%)";
  if (_isSaturatedRetained(segId, routes)) return "hsl(25,95%,53%)";
  if (routes.primary && routes.primary.segment_id === segId) return "hsl(142,71%,45%)";
  if (routes.secondary && routes.secondary.segment_id === segId) return "hsl(48,96%,53%)";
  const excluded = routes.excluded || [];
  if (excluded.some((e) => e.segment_id === segId && e.reason_code === "CLOSED")) return "hsl(0,84%,60%)";
  if (excluded.some((e) => e.segment_id === segId)) return "hsl(0,0%,22%)";
  return "hsl(0,0%,30%)";
}

function getNodeRadius(segId, routes) {
  if (!routes) return 6;
  if (routes.primary && routes.primary.segment_id === segId) return 9;
  if (routes.secondary && routes.secondary.segment_id === segId) return 8;
  const excluded = routes.excluded || [];
  if (excluded.some((e) => e.segment_id === segId && e.reason_code === "CLOSED")) return 9;
  return 6;
}

function updateMap(routes) {
  const container = document.getElementById("f4-map");
  if (container) renderMap(container, routes);
}
