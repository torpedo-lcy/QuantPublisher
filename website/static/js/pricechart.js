// 종목 페이지 가격 차트 (uPlot). 데이터는 charts/prices/<코드>.json
// 형식: {"code", "t": 일 단위 epoch[], "c": 종가[], "v": 거래량[]}
(function () {
  "use strict";

  var DEFAULT_VISIBLE_DAYS = 250; // 첫 화면에 보이는 거래일 수
  var MA_WINDOWS = [
    { n: 20, color: "#f59e0b" },
    { n: 60, color: "#16a34a" },
    { n: 120, color: "#9333ea" },
  ];

  function movingAverage(values, n) {
    var out = new Array(values.length).fill(null);
    var sum = 0;
    for (var i = 0; i < values.length; i++) {
      sum += values[i];
      if (i >= n) sum -= values[i - n];
      if (i >= n - 1) out[i] = sum / n;
    }
    return out;
  }

  var fmt = QPChart.fmt;
  var cssVar = QPChart.cssVar;

  function dateLabel(sec) {
    return new Date(sec * 1000).toISOString().slice(0, 10);
  }

  function render(el, data) {
    var priceEl = el.querySelector(".price-chart-price");
    var volumeEl = el.querySelector(".price-chart-volume");
    var legendEl = el.querySelector(".chart-legend");
    var statusEl = el.querySelector(".chart-status");

    var x = data.t.map(function (d) { return d * 86400; });
    var series = [data.c].concat(MA_WINDOWS.map(function (w) { return movingAverage(data.c, w.n); }));
    var width = Math.max(el.clientWidth, 280);
    var fg = cssVar("--fg", "#1b1f23");
    var grid = cssVar("--border", "#e1e4e8");
    var accent = cssVar("--accent", "#0b5fff");
    var muted = cssVar("--muted", "#6a737d");

    // 범례: 색 표시 + 이름 + 커서 위치(없으면 마지막 거래일)의 값.
    var legendItems = [{ label: "종가", color: accent, get: function (i) { return data.c[i]; } }]
      .concat(MA_WINDOWS.map(function (w, k) {
        return { label: "MA" + w.n, color: w.color, get: function (i) { return series[k + 1][i]; } };
      }))
      .concat([{ label: "거래량", color: muted, get: function (i) { return data.v[i]; } }]);

    var showLegendValues = QPChart.buildLegend(legendEl, legendItems);
    function showLegend(i) {
      showLegendValues(i, dateLabel(x[i]));
    }

    var start = Math.max(0, x.length - DEFAULT_VISIBLE_DAYS);
    var sync = uPlot.sync("pricechart-" + data.code);

    var axisBase = { stroke: fg, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } };

    var priceOpts = {
      width: width,
      height: 280,
      cursor: { sync: { key: sync.key } },
      scales: { x: { time: true, auto: false, min: x[start], max: x[x.length - 1] } },
      legend: { show: false },
      axes: [
        Object.assign({}, axisBase),
        Object.assign({}, axisBase, { size: 70, values: function (u, vals) { return vals.map(fmt); } }),
      ],
      series: [{}, { label: "종가", stroke: accent, width: 1.5 }].concat(
        MA_WINDOWS.map(function (w) { return { label: "MA" + w.n, stroke: w.color, width: 1 }; })
      ),
      hooks: {
        // 커서가 차트 밖에 있으면 마지막 거래일을 보여준다.
        setCursor: [function (u) {
          showLegend(u.cursor.idx == null ? x.length - 1 : u.cursor.idx);
        }],
      },
    };

    var volumeOpts = {
      width: width,
      height: 90,
      cursor: { sync: { key: sync.key } },
      scales: { x: { time: true, auto: false, min: x[start], max: x[x.length - 1] } },
      legend: { show: false },
      axes: [
        Object.assign({}, axisBase, { show: false }),
        Object.assign({}, axisBase, { size: 70, values: function (u, vals) { return vals.map(fmt); } }),
      ],
      series: [
        {},
        {
          label: "거래량",
          stroke: cssVar("--muted", "#6a737d"),
          fill: cssVar("--muted", "#6a737d"),
          width: 1,
          paths: uPlot.paths.bars({ size: [0.7, 20] }),
          points: { show: false },
        },
      ],
    };

    statusEl.remove();
    new uPlot(priceOpts, [x].concat(series), priceEl);
    new uPlot(volumeOpts, [x, data.v], volumeEl);
    showLegend(x.length - 1);
  }

  QPChart.mount(".price-chart", render);
})();
