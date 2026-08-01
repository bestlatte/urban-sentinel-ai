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

function renderMap(container, routes, incidentSegmentId = null) {
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
  
  // 定義事件點的動態光暈效果
  svg += `<defs>
    <radialGradient id="incident-glow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" style="stop-color:hsl(0,84%,60%);stop-opacity:0.8"/>
      <stop offset="100%" style="stop-color:hsl(0,84%,60%);stop-opacity:0"/>
    </radialGradient>
  </defs>`;

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
        const edgeColor = getEdgeColor(seg.segment_id, altId, routes, incidentSegmentId);
        const edgeDash = getEdgeDash(seg.segment_id, altId, routes);
        const edgeWidth = getEdgeWidth(seg.segment_id, altId, routes, incidentSegmentId);
        svg += `<line x1="${from.mx}" y1="${from.my}" x2="${to.mx}" y2="${to.my}" stroke="${edgeColor}" stroke-width="${edgeWidth}" stroke-dasharray="${edgeDash}" opacity="0.5"/>`;
      });
    });
  }

  // 繪製節點
  mappedPoints.forEach((p) => {
    const isIncident = p.segment_id === incidentSegmentId;
    const color = getSegmentColor(p.segment_id, routes, incidentSegmentId);
    const r = getNodeRadius(p.segment_id, routes, incidentSegmentId);
    
    // 事件發生點：加上動態光暈效果
    if (isIncident) {
      // 外圈光暈
      svg += `<circle cx="${p.mx}" cy="${p.my}" r="${r + 12}" fill="url(#incident-glow)" opacity="0.6">
        <animate attributeName="r" values="${r + 8};${r + 15};${r + 8}" dur="2s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.6;0.3;0.6" dur="2s" repeatCount="indefinite"/>
      </circle>`;
      // 中圈
      svg += `<circle cx="${p.mx}" cy="${p.my}" r="${r + 4}" fill="hsl(0,84%,60%)" opacity="0.3"/>`;
    }
    
    // 主節點
    svg += `<circle cx="${p.mx}" cy="${p.my}" r="${r}" fill="${color}" opacity="0.9"/>`;
    
    // 事件點加上 X 標記
    if (isIncident) {
      const xSize = r * 0.5;
      svg += `<line x1="${p.mx - xSize}" y1="${p.my - xSize}" x2="${p.mx + xSize}" y2="${p.my + xSize}" stroke="white" stroke-width="2" stroke-linecap="round"/>`;
      svg += `<line x1="${p.mx + xSize}" y1="${p.my - xSize}" x2="${p.mx - xSize}" y2="${p.my + xSize}" stroke="white" stroke-width="2" stroke-linecap="round"/>`;
    }
    
    // 標籤
    const label = (p.$note || p.segment_id).replace(/，.*/, "").replace(/（.*）/, "");
    const labelColor = isIncident ? "hsl(0,84%,70%)" : "hsl(0,0%,50%)";
    const labelWeight = isIncident ? "font-weight='600'" : "";
    svg += `<text x="${p.mx}" y="${p.my + r + 14}" text-anchor="middle" fill="${labelColor}" font-size="11" ${labelWeight} font-family="-apple-system,sans-serif">${escapeHtml(label)}</text>`;
  });

  svg += `</svg>`;

  // 圖例（加上事件點說明）
  const legend = `<div style="position:absolute;bottom:12px;right:16px;display:flex;gap:12px;font-size:0.65rem;color:hsl(0,0%,50%)">
    <span><span style="color:hsl(0,84%,60%)">✕</span> 事件</span>
    <span><span style="color:hsl(142,71%,45%)">●</span> 主線</span>
    <span><span style="color:hsl(48,96%,53%)">●</span> 次線</span>
    <span><span style="color:hsl(0,84%,60%)">●</span> 封閉</span>
    <span><span style="color:hsl(0,0%,30%)">●</span> 一般</span>
  </div>`;

  container.innerHTML = svg + legend;
}

function getEdgeColor(fromId, toId, routes, incidentSegmentId = null) {
  if (!routes) {
    // 沒有路線規劃時，事件路段的連線才變紅
    if (incidentSegmentId && (fromId === incidentSegmentId || toId === incidentSegmentId)) {
      return "hsl(0,84%,60%)";
    }
    return "hsl(0,0%,18%)";
  }
  
  const primary = routes.primary && routes.primary.segment_id;
  const secondary = routes.secondary && routes.secondary.segment_id;
  const closedIds = (routes.excluded || []).filter(e => e.reason_code === "CLOSED").map(e => e.segment_id);

  // ★ 疏散路線優先級最高（不被紅線覆蓋）
  // 主路線連線：綠色
  if ((fromId === primary && toId === secondary) || (toId === primary && fromId === secondary)) return "hsl(142,71%,45%)";
  if (fromId === primary || toId === primary) return "hsl(142,71%,45%)";
  // 次路線連線：黃色
  if (fromId === secondary || toId === secondary) return "hsl(48,96%,53%)";
  
  // 封閉路段連線：紅色
  if (closedIds.includes(fromId) || closedIds.includes(toId)) return "hsl(0,84%,60%)";
  
  // 事件路段連線（但不是疏散路線）：紅色
  if (incidentSegmentId && (fromId === incidentSegmentId || toId === incidentSegmentId)) {
    return "hsl(0,84%,60%)";
  }
  
  return "hsl(0,0%,18%)";
}

function getEdgeDash(fromId, toId, routes) {
  if (!routes) return "none";
  const secondary = routes.secondary && routes.secondary.segment_id;
  if (fromId === secondary || toId === secondary) return "4,3";
  return "none";
}

function getEdgeWidth(fromId, toId, routes, incidentSegmentId = null) {
  if (!routes) {
    // 沒有路線規劃時，事件路段的連線才加粗
    if (incidentSegmentId && (fromId === incidentSegmentId || toId === incidentSegmentId)) {
      return "3";
    }
    return "1";
  }
  
  const primary = routes.primary && routes.primary.segment_id;
  const secondary = routes.secondary && routes.secondary.segment_id;
  const closedIds = (routes.excluded || []).filter(e => e.reason_code === "CLOSED").map(e => e.segment_id);
  
  // ★ 疏散路線優先級最高
  if (fromId === primary || toId === primary) return "2";
  if (fromId === secondary || toId === secondary) return "1.5";
  
  // 封閉路段
  if (closedIds.includes(fromId) || closedIds.includes(toId)) return "2.5";
  
  // 事件路段（但不是疏散路線）
  if (incidentSegmentId && (fromId === incidentSegmentId || toId === incidentSegmentId)) {
    return "3";
  }
  
  return "1";
}

function _isSaturatedRetained(segId, routes) {
  const findings = (routes && routes.findings) || [];
  return findings.some(
    (f) => f.finding_code === "SATURATED_BUT_RETAINED" && (f.segment_ids || []).includes(segId)
  );
}

function getSegmentColor(segId, routes, incidentSegmentId = null) {
  // ★ 事件發生路段：紅色（最高優先級）
  if (segId === incidentSegmentId) {
    return "hsl(0, 84%, 60%)";
  }
  
  // 優先檢查飽和資料
  const satData = _saturationMapData[segId];
  if (satData && satData.level !== "normal") {
    // 但如果是路線規劃結果中的主/次路線，優先顯示路線顏色
    if (routes) {
      if (routes.primary && routes.primary.segment_id === segId) return "hsl(142,71%,45%)";
      if (routes.secondary && routes.secondary.segment_id === segId) return "hsl(48,96%,53%)";
    }
    // 飽和但不是路線：顯示飽和顏色
    if (satData.level === "A") return "hsl(0, 84%, 60%)";
    if (satData.level === "B") return "hsl(25, 95%, 53%)";
  }
  
  if (!routes) return "hsl(0,0%,30%)";
  if (_isSaturatedRetained(segId, routes)) return "hsl(25,95%,53%)";
  if (routes.primary && routes.primary.segment_id === segId) return "hsl(142,71%,45%)";
  if (routes.secondary && routes.secondary.segment_id === segId) return "hsl(48,96%,53%)";
  const excluded = routes.excluded || [];
  if (excluded.some((e) => e.segment_id === segId && e.reason_code === "CLOSED")) return "hsl(0,84%,60%)";
  if (excluded.some((e) => e.segment_id === segId)) return "hsl(0,0%,22%)";
  return "hsl(0,0%,30%)";
}

function getNodeRadius(segId, routes, incidentSegmentId = null) {
  // ★ 事件發生路段：最大半徑
  if (segId === incidentSegmentId) {
    return 11;
  }
  
  // 優先檢查飽和資料
  const satData = _saturationMapData[segId];
  if (satData && satData.level !== "normal") {
    // 飽和的節點放大
    if (satData.level === "A") return 9;
    if (satData.level === "B") return 8;
  }
  
  if (!routes) return 6;
  if (routes.primary && routes.primary.segment_id === segId) return 9;
  if (routes.secondary && routes.secondary.segment_id === segId) return 8;
  const excluded = routes.excluded || [];
  if (excluded.some((e) => e.segment_id === segId && e.reason_code === "CLOSED")) return 9;
  return 6;
}

function updateMap(routes, incidentSegmentId = null) {
  const container = document.getElementById("f4-map");
  if (container) {
    _lastRoutes = routes; // 記憶最後的路線規劃結果
    _lastIncidentSegmentId = incidentSegmentId; // 記憶事件發生路段
    renderMap(container, routes, incidentSegmentId);
  }
}

// 記憶最後的路線規劃結果，供飽和更新時使用
let _lastRoutes = null;
// 記憶事件發生的路段 ID
let _lastIncidentSegmentId = null;

// ========== Saturation Map ==========

// 地圖飽和資料：所有路段的即時飽和度（用於渲染地圖顏色）
let _saturationMapData = {};

// 警報列表資料：只記錄達到飽和閾值觸發警報的路段
let _saturationAlertList = {};

/**
 * 更新地圖飽和資料（不影響警報列表）
 */
function updateSaturationMapData(segmentId, name, saturationScore, timestamp) {
  let level = "normal";
  if (saturationScore >= 0.95) level = "A";
  else if (saturationScore >= 0.85) level = "B";
  
  _saturationMapData[segmentId] = {
    name: name || segmentId,
    saturation_score: saturationScore,
    level,
    timestamp: timestamp || new Date().toISOString(),
  };
}

/**
 * 新增警報到列表（只有收到 decision.alert.v1 時呼叫）
 */
function addSaturationAlert(segmentId, name, saturationScore, timestamp) {
  let level = "normal";
  if (saturationScore >= 0.95) level = "A";
  else if (saturationScore >= 0.85) level = "B";
  
  // 只有 A 或 B 級才加入警報列表
  if (level === "normal") return;
  
  _saturationAlertList[segmentId] = {
    name: name || segmentId,
    saturation_score: saturationScore,
    level,
    timestamp: timestamp || new Date().toISOString(),
  };
  
  // 同時更新地圖資料
  updateSaturationMapData(segmentId, name, saturationScore, timestamp);
  
  // 無論在哪個頁面，都要更新資料和渲染
  renderSaturationMap();
  renderSaturationAlertList();
  // 同時更新 Dashboard 頁面的飽和列表
  renderDashboardSaturationList();
  // 更新 F4 路網圖（使用上次的路線規劃結果，保留主/次路線顯示）
  const f4Container = document.getElementById("f4-map");
  if (f4Container) {
    renderMap(f4Container, _lastRoutes);
  }
}

/**
 * 批次更新地圖飽和資料（從 traffic_samples 陣列，只更新地圖不更新列表）
 */
function updateSaturationFromSamples(samples) {
  if (!Array.isArray(samples)) return;
  samples.forEach((s) => {
    if (s.segment_id && typeof s.saturation_score === "number") {
      const name = s.road_name || s.segment_id;
      updateSaturationMapData(s.segment_id, name, s.saturation_score, s.timestamp);
    }
  });
  renderSaturationMap();
  // 注意：不呼叫 renderSaturationAlertList()，列表只由警報觸發更新
}

/**
 * 舊版相容：updateSaturationData 改為只更新地圖
 */
function updateSaturationData(segmentId, name, saturationScore, timestamp) {
  updateSaturationMapData(segmentId, name, saturationScore, timestamp);
}

/**
 * 從 DecisionResult.routes.candidates 批次更新飽和資料（只更新地圖）
 */
function updateSaturationFromCandidates(candidates) {
  if (!Array.isArray(candidates)) return;
  candidates.forEach((c) => {
    if (c.segment_id && typeof c.saturation_score === "number") {
      const name = c.name || c.segment_id;
      const timestamp = c.snapshot_at || new Date().toISOString();
      updateSaturationMapData(c.segment_id, name, c.saturation_score, timestamp);
    }
  });
  renderSaturationMap();
}

/**
 * 清空所有飽和資料（重置系統）
 */
function clearSaturationData() {
  _saturationMapData = {};
  _saturationAlertList = {};
  _lastRoutes = null; // 清空路線規劃記憶
  renderSaturationMap();
  renderSaturationAlertList();
  renderDashboardSaturationList();
  // 重新渲染 F4 路網圖（恢復到無路線狀態）
  const f4Container = document.getElementById("f4-map");
  if (f4Container) {
    renderMap(f4Container, null);
  }
}

/**
 * 重置飽和資料（由前端重置按鈕呼叫）
 */
function resetSaturationData() {
  clearSaturationData();
}

/**
 * 渲染飽和地圖（根據 _saturationMapData 顯示所有路段狀態）
 */
function renderSaturationMap() {
  const container = document.getElementById("saturation-map");
  if (!container) return;
  
  if (!mapGeometry) {
    container.innerHTML = `<div style="color:hsl(0,0%,40%);text-align:center;padding:60px 0;font-size:0.9rem">Road network loading...</div>`;
    return;
  }

  const vb = "0 0 800 600";
  const rawPoints = mapGeometry.display_points || [];
  
  // 計算座標映射
  const xs = rawPoints.map(p => p.x);
  const ys = rawPoints.map(p => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const padX = 80, padY = 60;
  const scaleX = (800 - padX * 2) / (maxX - minX || 1);
  const scaleY = (600 - padY * 2) / (maxY - minY || 1);

  const mappedPoints = rawPoints.map(p => ({
    ...p,
    mx: padX + (p.x - minX) * scaleX,
    my: padY + (p.y - minY) * scaleY,
  }));
  
  const posMap = {};
  mappedPoints.forEach((p) => { posMap[p.segment_id] = p; });

  let svg = `<svg viewBox="${vb}" style="width:100%;height:100%" xmlns="http://www.w3.org/2000/svg">`;
  
  // 定義虛線 pattern
  svg += `<defs>
    <pattern id="dash-a" patternUnits="userSpaceOnUse" width="12" height="12">
      <circle cx="3" cy="6" r="2.5" fill="hsl(0, 84%, 60%)"/>
    </pattern>
    <pattern id="dash-b" patternUnits="userSpaceOnUse" width="12" height="12">
      <circle cx="3" cy="6" r="2.5" fill="hsl(25, 95%, 53%)"/>
    </pattern>
  </defs>`;

  // 繪製連線（根據飽和狀態變色）
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
        
        // 判斷兩端飽和狀態，取較高者
        const fromData = _saturationMapData[seg.segment_id];
        const toData = _saturationMapData[altId];
        const fromLevel = fromData?.level || "normal";
        const toLevel = toData?.level || "normal";
        
        // 決定線條顏色與樣式
        let edgeColor = "hsl(0,0%,25%)";
        let strokeWidth = "1.5";
        let dashArray = "none";
        let opacity = "0.4";
        
        // 如果任一端是 A 級或 B 級，整條線變色
        if (fromLevel === "A" || toLevel === "A") {
          edgeColor = "hsl(0, 84%, 60%)";
          strokeWidth = "4";
          dashArray = "8,6";
          opacity = "0.9";
        } else if (fromLevel === "B" || toLevel === "B") {
          edgeColor = "hsl(25, 95%, 53%)";
          strokeWidth = "3";
          dashArray = "6,4";
          opacity = "0.8";
        }
        
        svg += `<line x1="${from.mx}" y1="${from.my}" x2="${to.mx}" y2="${to.my}" 
                      stroke="${edgeColor}" stroke-width="${strokeWidth}" 
                      stroke-dasharray="${dashArray}" opacity="${opacity}"
                      stroke-linecap="round"/>`;
      });
    });
  }

  // 繪製節點
  mappedPoints.forEach((p) => {
    const data = _saturationMapData[p.segment_id];
    const level = data?.level || "normal";
    const satScore = data?.saturation_score;
    
    let color, r, strokeColor, strokeWidth;
    if (level === "A") {
      color = "hsl(0, 84%, 60%)";
      r = 14;
      strokeColor = "hsl(0, 84%, 75%)";
      strokeWidth = 3;
    } else if (level === "B") {
      color = "hsl(25, 95%, 53%)";
      r = 12;
      strokeColor = "hsl(25, 95%, 70%)";
      strokeWidth = 2;
    } else {
      color = "hsl(160, 60%, 45%)";
      r = 8;
      strokeColor = "none";
      strokeWidth = 0;
    }
    
    // 繪製外圈（飽和時有光暈效果）
    if (level !== "normal") {
      svg += `<circle cx="${p.mx}" cy="${p.my}" r="${r + 6}" fill="${color}" opacity="0.2"/>`;
    }
    
    // 繪製主節點
    svg += `<circle cx="${p.mx}" cy="${p.my}" r="${r}" fill="${color}" 
                    stroke="${strokeColor}" stroke-width="${strokeWidth}" opacity="0.95"/>`;
    
    // 標籤
    const label = (p.$note || p.segment_id).replace(/，.*/, "").replace(/（.*）/, "");
    svg += `<text x="${p.mx}" y="${p.my + r + 18}" text-anchor="middle" 
                  fill="hsl(0,0%,65%)" font-size="12" font-weight="500"
                  font-family="-apple-system,sans-serif">${escapeHtml(label)}</text>`;
    
    // 飽和度數字（只顯示有資料的）
    if (satScore !== undefined) {
      const pctText = (satScore * 100).toFixed(0) + "%";
      svg += `<text x="${p.mx}" y="${p.my + 4}" text-anchor="middle" 
                    fill="white" font-size="10" font-weight="600"
                    font-family="-apple-system,sans-serif">${pctText}</text>`;
    }
  });

  svg += `</svg>`;
  container.innerHTML = svg;
}

/**
 * 渲染飽和警報列表（右側 sidebar，只顯示觸發過警報的路段）
 */
function renderSaturationAlertList() {
  const list = document.getElementById("saturation-list");
  if (!list) return;
  
  // 從警報列表取資料（只有 A 或 B 級）
  const alertedSegments = Object.entries(_saturationAlertList)
    .sort((a, b) => {
      // A 級排前面，同級別按飽和度降序
      if (a[1].level !== b[1].level) return a[1].level === "A" ? -1 : 1;
      return b[1].saturation_score - a[1].saturation_score;
    });
  
  if (alertedSegments.length === 0) {
    list.innerHTML = '<div class="saturation-empty">目前無飽和路段</div>';
    return;
  }
  
  let html = "";
  alertedSegments.forEach(([segId, data]) => {
    const levelClass = data.level === "A" ? "level-a" : "level-b";
    const pct = (data.saturation_score * 100).toFixed(1);
    const timeStr = data.timestamp ? new Date(data.timestamp).toLocaleTimeString("zh-TW", {hour: "2-digit", minute: "2-digit"}) : "";
    
    html += `
      <div class="saturation-item ${levelClass}">
        <div class="saturation-item-header">
          <span class="saturation-item-level">${data.level} 級</span>
          <span class="saturation-item-time">${timeStr}</span>
        </div>
        <div class="saturation-item-name">${escapeHtml(data.name)}</div>
        <div class="saturation-item-score">飽和度 ${pct}%</div>
      </div>
    `;
  });
  
  list.innerHTML = html;
}

/**
 * 舊版相容：renderSaturationList 轉呼叫新函數
 */
function renderSaturationList() {
  renderSaturationAlertList();
}

/**
 * 初始化飽和地圖頁面
 */
function initSaturationMap() {
  renderSaturationMap();
  renderSaturationAlertList();
  renderDashboardSaturationList();
}

/**
 * 渲染 Dashboard 頁面的飽和路段列表（簡化版，顯示在 Dashboard 右側）
 */
function renderDashboardSaturationList() {
  const list = document.getElementById("dashboard-saturation-list");
  if (!list) return;
  
  // 從警報列表取資料（只有 A 或 B 級）
  const alertedSegments = Object.entries(_saturationAlertList)
    .sort((a, b) => {
      // A 級排前面，同級別按飽和度降序
      if (a[1].level !== b[1].level) return a[1].level === "A" ? -1 : 1;
      return b[1].saturation_score - a[1].saturation_score;
    });
  
  if (alertedSegments.length === 0) {
    list.innerHTML = '<div class="saturation-empty">目前無飽和路段</div>';
    return;
  }
  
  let html = "";
  alertedSegments.forEach(([segId, data]) => {
    const levelClass = data.level === "A" ? "level-a" : "level-b";
    const pct = (data.saturation_score * 100).toFixed(0);
    const timeStr = data.timestamp ? new Date(data.timestamp).toLocaleTimeString("zh-TW", {hour: "2-digit", minute: "2-digit"}) : "";
    
    html += `
      <div class="dashboard-saturation-item ${levelClass}">
        <div class="dashboard-saturation-item-main">
          <span class="dashboard-saturation-item-level">${data.level}</span>
          <span class="dashboard-saturation-item-name">${escapeHtml(data.name)}</span>
        </div>
        <div class="dashboard-saturation-item-detail">
          <span class="dashboard-saturation-item-score">${pct}%</span>
          <span class="dashboard-saturation-item-time">${timeStr}</span>
        </div>
      </div>
    `;
  });
  
  list.innerHTML = html;
}
