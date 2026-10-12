// 종목 페이지 재무 시계열 차트 (uPlot). 데이터는 charts/financials/<코드>.json
// 형식: {"code", "y": 연도[], "s": 매출액[], "o": 영업이익[], "n": 순이익[]} (억원, 없으면 null)
(function () {
  "use strict";

  function render(el, data) {
    var plotEl = el.querySelector(".financial-chart-plot");
    var legendEl = el.querySelector(".chart-legend");
    var statusEl = el.querySelector(".chart-status");
    var cssVar = QPChart.cssVar;
    var fmtEok = QPChart.fmtEok;

    var fg = cssVar("--fg", "#1b1f23");
    var grid = cssVar("--border", "#e1e4e8");
    var defs = [
      { label: "매출액", color: cssVar("--accent", "#0b5fff"), values: data.s },
      { label: "영업이익", color: "#16a34a", values: data.o },
      { label: "순이익", color: "#f59e0b", values: data.n },
    ];

    var show = QPChart.buildLegend(
      legendEl,
      defs.map(function (d) {
        return { label: d.label, color: d.color, format: fmtEok, get: function (i) { return d.values[i]; } };
      })
    );
    function showLegend(i) { show(i, data.y[i] + "년"); }

    var axisBase = { stroke: fg, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } };
    var last = data.y.length - 1;
    // 항목마다 단위가 크게 달라 패널을 나누고, 연도 축과 커서를 맞춰 위아래로 쌓는다.
    var syncKey = uPlot.sync("financial-" + data.code);
    var panelHeight = 150;
    var xAxisHeight = 40;

    defs.forEach(function (d, k) {
      var isLast = k === defs.length - 1;
      var panelEl = document.createElement("div");
      panelEl.className = "financial-chart-panel";
      plotEl.appendChild(panelEl);
      var opts = {
        width: Math.max(el.clientWidth, 280),
        height: panelHeight + (isLast ? xAxisHeight : 0),
        legend: { show: false },
        cursor: { sync: { key: syncKey.key, setSeries: false } },
        // 연도는 정수 눈금만 쓴다 (시간 축이 아님). 양끝에 반 칸씩 여백을 두어 끝 연도 라벨이
        // 플롯 밖으로 나가지 않게 한다 (나가면 x축이 있는 마지막 패널만 폭이 달라진다).
        scales: { x: { time: false, range: [data.y[0] - 0.5, data.y[last] + 0.5] } },
        axes: [
          Object.assign({}, axisBase, {
            show: isLast,
            splits: function () { return data.y; },
            values: function (u, vals) { return vals.map(String); },
          }),
          Object.assign({}, axisBase, { size: 70, values: function (u, vals) { return vals.map(fmtEok); } }),
        ],
        series: [
          {},
          { label: d.label, stroke: d.color, width: 2, points: { show: true, size: 6, fill: d.color } },
        ],
        hooks: {
          // 커서가 차트 밖에 있으면 가장 최근 연도를 보여준다.
          setCursor: [function (u) { showLegend(u.cursor.idx == null ? last : u.cursor.idx); }],
        },
      };
      new uPlot(opts, [data.y, d.values], panelEl);
    });

    statusEl.remove();
    showLegend(last);
  }

  QPChart.mount(".financial-chart", render);
})();
