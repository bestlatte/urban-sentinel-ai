/** Traffic Flow charts powered by the bundled Chart.js build. */

let trafficChart = null;
let rawTrafficFlowData = null;
let rawTrafficFlowPromise = null;
let roadTopologyData = null;
let roadTopologyPromise = null;

function replaceTrafficChart(config) {
  const canvas = document.getElementById("traffic-chart");
  if (!canvas || typeof Chart === "undefined") return null;
  if (trafficChart) trafficChart.destroy();
  trafficChart = new Chart(canvas.getContext("2d"), config);
  return trafficChart;
}

function trendChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      y: {
        min: 0,
        max: 1.1,
        grid: { color: "rgba(107, 73, 50, 0.10)" },
        ticks: { color: "#665244", font: { size: 10 } },
      },
      x: {
        grid: { color: "rgba(107, 73, 50, 0.07)" },
        ticks: { color: "#665244", font: { size: 10 }, maxRotation: 0 },
      },
    },
  };
}

function initCharts() {
  const container = document.getElementById("f1-charts");
  if (!container || typeof Chart === "undefined") return;

  const canvas = document.createElement("canvas");
  canvas.id = "traffic-chart";
  canvas.style.width = "100%";
  canvas.style.height = "180px";
  container.appendChild(canvas);

  trafficChart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: [],
      datasets: [{
        label: "平均飽和度",
        data: [],
        borderColor: "#6B4932",
        backgroundColor: "rgba(107, 73, 50, 0.08)",
        tension: 0.4,
        fill: true,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 3,
      }],
    },
    options: trendChartOptions(),
  });
}

function updateChartData(trafficSamples) {
  if (!trafficChart || !Array.isArray(trafficSamples)) return;
  const timeMap = {};
  trafficSamples.forEach((sample) => {
    const time = sample.timestamp ? sample.timestamp.slice(11, 16) : "";
    if (!timeMap[time]) timeMap[time] = [];
    timeMap[time].push(sample.saturation_score);
  });

  const times = Object.keys(timeMap).sort();
  const lineData = {
    labels: times,
    datasets: [{
    label: "平均飽和度",
    data: times.map((time) => {
      const values = timeMap[time];
      return values.reduce((sum, value) => sum + value, 0) / values.length;
    }),
    borderColor: "#6B4932",
    backgroundColor: "rgba(107, 73, 50, 0.08)",
    tension: 0.4,
    fill: true,
    borderWidth: 1.5,
    pointRadius: 0,
    pointHoverRadius: 3,
    }],
  };
  if (trafficChart.config.type !== "line") {
    replaceTrafficChart({ type: "line", data: lineData, options: trendChartOptions() });
  } else {
    trafficChart.data = lineData;
    trafficChart.options = trendChartOptions();
    trafficChart.update();
  }
  setTrafficChartHeader("Traffic Flow");
}

async function loadRawTrafficFlowData() {
  if (rawTrafficFlowData) return rawTrafficFlowData;
  if (!rawTrafficFlowPromise) {
    rawTrafficFlowPromise = fetch("/data/city_traffic_flow.json")
      .then((response) => {
        if (!response.ok) throw new Error(`Traffic data HTTP ${response.status}`);
        return response.json();
      })
      .then((rows) => {
        rawTrafficFlowData = Array.isArray(rows) ? rows : [];
        return rawTrafficFlowData;
      })
      .catch((error) => {
        rawTrafficFlowPromise = null;
        throw error;
      });
  }
  return rawTrafficFlowPromise;
}

async function loadRoadTopologyData() {
  if (roadTopologyData) return roadTopologyData;
  if (!roadTopologyPromise) {
    roadTopologyPromise = fetch("/data/road_network_topology.json")
      .then((response) => {
        if (!response.ok) throw new Error(`Road topology HTTP ${response.status}`);
        return response.json();
      })
      .then((roads) => {
        roadTopologyData = Array.isArray(roads) ? roads : [];
        return roadTopologyData;
      })
      .catch((error) => {
        roadTopologyPromise = null;
        throw error;
      });
  }
  return roadTopologyPromise;
}

function getIncidentRoadId(incident) {
  if (String(incident?.affected_road || "").startsWith("RD_")) return incident.affected_road;
  if (String(incident?.affected_segment || "").startsWith("RD_")) return incident.affected_segment;
  return null;
}

function parseTrafficTimestamp(value) {
  if (!value) return null;
  const parsed = new Date(String(value).replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function setTrafficChartHeader(text) {
  const header = document.querySelector("#f1-charts .section-header");
  if (header) header.textContent = text;
}

async function updateTrafficChartForIncident(decision) {
  if (!trafficChart || !decision?.incident) return;

  try {
    const [rows, topology] = await Promise.all([
      loadRawTrafficFlowData(),
      loadRoadTopologyData(),
    ]);
    if (!rows.length) return;

    const incidentRoadId = getIncidentRoadId(decision.incident);
    const incidentRoad = topology.find((road) => road.segment_id === incidentRoadId);
    const relatedRoadIds = new Set([
      incidentRoadId,
      ...(incidentRoad?.alternatives || []),
    ].filter(Boolean));
    if (!relatedRoadIds.size) return;

    const incidentTime = parseTrafficTimestamp(decision.incident.timestamp);
    const availableTimes = [...new Set(rows
      .filter((row) => relatedRoadIds.has(row.Segment_ID))
      .map((row) => row.Timestamp)
      .filter(Boolean))];
    let selectedTime = availableTimes[availableTimes.length - 1];
    if (incidentTime && availableTimes.length) {
      selectedTime = availableTimes.reduce((closest, candidate) => {
        const closestDate = parseTrafficTimestamp(closest);
        const candidateDate = parseTrafficTimestamp(candidate);
        if (!candidateDate) return closest;
        if (!closestDate) return candidate;
        return Math.abs(candidateDate - incidentTime) < Math.abs(closestDate - incidentTime) ? candidate : closest;
      }, availableTimes[0]);
    }

    const snapshot = rows
      .filter((row) => row.Timestamp === selectedTime && relatedRoadIds.has(row.Segment_ID))
      .sort((a, b) => {
        if (a.Segment_ID === incidentRoadId) return -1;
        if (b.Segment_ID === incidentRoadId) return 1;
        return String(a.Segment_ID).localeCompare(String(b.Segment_ID));
      });
    if (!snapshot.length) return;

    const barChart = replaceTrafficChart({
      type: "bar",
      data: {
        labels: snapshot.map((row) => `${row.Road_Name || row.Segment_ID}${row.Segment_ID === incidentRoadId ? "（事件）" : "（相鄰）"}`),
        datasets: [
      {
        label: "Avg Speed (km/h)",
        data: snapshot.map((row) => row.Avg_Speed),
        yAxisID: "ySpeed",
        backgroundColor: "rgba(107, 73, 50, 0.78)",
        borderColor: "#6B4932",
        borderWidth: 1,
        borderRadius: 5,
        maxBarThickness: 26,
      },
      {
        label: "Saturation Score",
        data: snapshot.map((row) => row.Saturation_Score),
        yAxisID: "ySaturation",
        backgroundColor: "rgba(185, 107, 59, 0.72)",
        borderColor: "#A85E34",
        borderWidth: 1,
        borderRadius: 5,
        maxBarThickness: 26,
      },
        ],
      },
      options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          position: "top",
          align: "end",
          labels: { color: "#665244", boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 10 } },
        },
        tooltip: {
          callbacks: {
            title(items) {
              const row = snapshot[items[0]?.dataIndex];
              if (!row) return "";
              const relation = row.Segment_ID === incidentRoadId ? "事件路段" : "相鄰受影響路段";
              return `${row.Road_Name} · ${row.Segment_ID} · ${relation}`;
            },
            afterBody(items) {
              const row = snapshot[items[0]?.dataIndex];
              return row ? [`車流量 ${row.Vehicle_Count ?? "—"}`, `車道狀態 ${row.Lane_Status || "—"}`] : [];
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#665244", font: { size: 9 }, maxRotation: 35, minRotation: 0 } },
        ySpeed: {
          beginAtZero: true,
          position: "left",
          suggestedMax: 60,
          grid: { color: "rgba(107, 73, 50, 0.10)" },
          ticks: { color: "#665244", font: { size: 9 } },
          title: { display: true, text: "km/h", color: "#665244", font: { size: 9 } },
        },
        ySaturation: {
          beginAtZero: true,
          min: 0,
          max: 1,
          position: "right",
          grid: { drawOnChartArea: false },
          ticks: { color: "#A85E34", font: { size: 9 } },
          title: { display: true, text: "Saturation", color: "#A85E34", font: { size: 9 } },
        },
      },
      },
    });
    if (!barChart) return;

    const eventId = decision.incident.event_id || "事件";
    setTrafficChartHeader(`Traffic Flow · ${eventId} · 事件與相鄰路段 · ${selectedTime?.slice(11, 16) || ""}`);
    barChart.update();
  } catch (error) {
    console.warn("事件 Traffic Flow 長條圖載入失敗:", error);
  }
}
