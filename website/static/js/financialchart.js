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
    var opts = {
      width: Math.max(el.clientWidth, 280),
      height: 260,
      legend: { show: false },
      // 연도는 정수 눈금만 쓴다 (시간 축이 아님).
      scales: { x: { time: false } },
      axes: [
        Object.assign({}, axisBase, {
          splits: function () { return data.y; },
          values: function (u, vals) { return vals.map(String); },
        }),
        Object.assign({}, axisBase, { size: 70, values: function (u, vals) { return vals.map(fmtEok); } }),
      ],
      series: [{}].concat(defs.map(function (d) {
        return { label: d.label, stroke: d.color, width: 2, points: { show: true, size: 6, fill: d.color } };
      })),
      hooks: {
        // 커서가 차트 밖에 있으면 가장 최근 연도를 보여준다.
        setCursor: [function (u) {
          showLegend(u.cursor.idx == null ? data.y.length - 1 : u.cursor.idx);
        }],
      },
    };

    statusEl.remove();
    new uPlot(opts, [data.y].concat(defs.map(function (d) { return d.values; })), plotEl);
    showLegend(data.y.length - 1);
  }

  QPChart.mount(".financial-chart", render);
})();
