/**
 * Chart.js 車流／人流時序圖與門檻線。
 * 門檻線：0.85（B級）/ 0.95（A級），來自 02-data-contract.md §4。
 * Chart.js 從 frontend/vendor/chart.umd.js 載入。
 */

let trafficChart = null;

function initCharts() {
  const ctx = document.getElementById("f1-charts");
  if (!ctx || typeof Chart === "undefined") return;

  const canvas = document.createElement("canvas");
  canvas.id = "traffic-chart";
  canvas.style.width = "100%";
  canvas.style.height = "180px";
  ctx.appendChild(canvas);

  trafficChart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "平均飽和度",
          data: [],
          borderColor: "#06b6d4",
          backgroundColor: "rgba(6, 182, 212, 0.1)",
          tension: 0.3,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        annotation: {
          annotations: {
            lineB: {
              type: "line",
              yMin: 0.85,
              yMax: 0.85,
              borderColor: "var(--level-b, #f97316)",
              borderWidth: 1,
              borderDash: [4, 4],
              label: { content: "B級 0.85", display: true, position: "start" },
            },
            lineA: {
              type: "line",
              yMin: 0.95,
              yMax: 0.95,
              borderColor: "var(--level-a, #dc2626)",
              borderWidth: 1,
              borderDash: [4, 4],
              label: { content: "A級 0.95", display: true, position: "start" },
            },
          },
        },
      },
      scales: {
        y: { min: 0, max: 1.1, title: { display: true, text: "飽和度" } },
        x: { title: { display: true, text: "時間" } },
      },
    },
  });
}

function updateChartData(trafficSamples) {
  if (!trafficChart || !trafficSamples) return;

  // 計算每個時間點的平均飽和度
  const timeMap = {};
  trafficSamples.forEach((s) => {
    const t = s.timestamp ? s.timestamp.slice(11, 16) : "";
    if (!timeMap[t]) timeMap[t] = [];
    timeMap[t].push(s.saturation_score);
  });

  const sorted = Object.keys(timeMap).sort();
  const avgData = sorted.map((t) => {
    const vals = timeMap[t];
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  });

  trafficChart.data.labels = sorted;
  trafficChart.data.datasets[0].data = avgData;
  trafficChart.update();
}
