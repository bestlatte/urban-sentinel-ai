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
          borderColor: "hsl(0, 0%, 65%)",
          backgroundColor: "hsla(0, 0%, 65%, 0.05)",
          tension: 0.4,
          fill: true,
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        annotation: {
          annotations: {
            lineB: {
              type: "line",
              yMin: 0.85,
              yMax: 0.85,
              borderColor: "hsl(25, 95%, 53%)",
              borderWidth: 1,
              borderDash: [4, 4],
              label: { content: "B  0.85", display: true, position: "start", font: { size: 9 }, color: "hsl(25, 95%, 53%)" },
            },
            lineA: {
              type: "line",
              yMin: 0.95,
              yMax: 0.95,
              borderColor: "hsl(0, 84%, 60%)",
              borderWidth: 1,
              borderDash: [4, 4],
              label: { content: "A  0.95", display: true, position: "start", font: { size: 9 }, color: "hsl(0, 84%, 60%)" },
            },
          },
        },
      },
      scales: {
        y: {
          min: 0,
          max: 1.1,
          grid: { color: "hsl(0, 0%, 10%)" },
          ticks: { color: "hsl(0, 0%, 40%)", font: { size: 10 } },
          title: { display: false },
        },
        x: {
          grid: { color: "hsl(0, 0%, 8%)" },
          ticks: { color: "hsl(0, 0%, 40%)", font: { size: 10 }, maxRotation: 0 },
          title: { display: false },
        },
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
