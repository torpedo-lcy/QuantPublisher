// 종목 페이지 가격 차트 (uPlot). 데이터는 charts/prices/<코드>.json
// 형식: {"code", "t": 일 단위 epoch[], "c": 종가[], "v": 거래량[]}
// data-index-src가 있으면 시장 대표지수(charts/index/<시장>.json, {"code","t","c"})를 겹쳐 그린다:
// 보이는 구간의 첫 거래일에서 종목과 지수가 같은 점에서 출발하도록 오른쪽 축 범위를 맞춘다
// (왼쪽 축 = 종목 가격, 오른쪽 축 = 지수 포인트).
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

  var INDEX_COLOR = "#e11d48";

  // 지수 일봉을 종목의 거래일에 맞춘다 (지수 중간에 빠진 날은 직전 값, 지수 시작 전과 마지막 날 이후는 null).
  function alignIndex(data, index) {
    var out = new Array(data.t.length).fill(null);
    var j = 0;
    var current = null;
    for (var i = 0; i < data.t.length; i++) {
      while (j < index.t.length && index.t[j] <= data.t[i]) {
        current = index.c[j];
        j++;
      }
      out[i] = data.t[i] > index.t[index.t.length - 1] ? null : current;
    }
    return out;
  }

  function changeText(value, base) {
    if (value == null || !base) return "";
    var pct = (value / base - 1) * 100;
    return " (" + (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%)";
  }

  // 지수 데이터가 있으면 불러와 render에 넘긴다. 실패하면 지수 없이 그린다.
  function load(el, data) {
    var src = el.getAttribute("data-index-src");
    if (!src) return render(el, data, null);
    return fetch(src)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (index) { return render(el, data, index); })
      .catch(function (err) {
        console.error("pricechart index overlay failed", err);
        return render(el, data, null);
      });
  }

  function dateLabel(sec) {
    return new Date(sec * 1000).toISOString().slice(0, 10);
  }

  function render(el, data, indexData) {
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
    var indexName = el.getAttribute("data-index-name");
    var ix = indexData ? alignIndex(data, indexData) : null;
    var start = Math.max(0, x.length - DEFAULT_VISIBLE_DAYS);
    var base = { i: start }; // 지수 비교의 기준 거래일 (보이는 구간의 첫 거래일)
    var shown = x.length - 1;

    // 지수를 겹칠 때는 기준일 대비 변화율을 값 옆에 붙여 정규화된 비교를 숫자로도 보여준다.
    var closeItem = { label: "종가", color: accent, get: function (i) { return data.c[i]; } };
    var legendItems = [closeItem];
    if (ix) {
      closeItem.format = function (v) { return fmt(v) + changeText(v, data.c[base.i]); };
      legendItems.push({
        label: indexName,
        color: INDEX_COLOR,
        get: function (i) { return ix[i]; },
        format: function (v) { return v == null ? "-" : fmt(v) + changeText(v, ix[base.i]); },
      });
    }
    legendItems = legendItems
      .concat(MA_WINDOWS.map(function (w, k) {
        return { label: "MA" + w.n, color: w.color, get: function (i) { return series[k + 1][i]; } };
      }))
      .concat([{ label: "거래량", color: muted, get: function (i) { return data.v[i]; } }]);

    var showLegendValues = QPChart.buildLegend(legendEl, legendItems);
    function showLegend(i) {
      shown = i;
      showLegendValues(i, dateLabel(x[i]));
    }

    var sync = uPlot.sync("pricechart-" + data.code);

    var axisBase = { stroke: fg, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } };

    // 보이는 구간 기준으로 왼쪽(가격)/오른쪽(지수) 축 범위를 구한다. 기준일의 종가와 지수가 같은
    // 높이가 되도록 오른쪽 범위 = 왼쪽 범위 x (기준일 지수 / 기준일 종가). 보이는 구간에 지수가
    // 없으면 null.
    function indexRanges(xmin, xmax) {
      var first = 0;
      while (first < x.length && (x[first] < xmin || ix[first] == null)) first++;
      if (first >= x.length) return null;
      var k = ix[first] / data.c[first];
      var lo = Infinity;
      var hi = -Infinity;
      for (var i = first; i < x.length && x[i] <= xmax; i++) {
        lo = Math.min(lo, data.c[i]);
        hi = Math.max(hi, data.c[i]);
        if (ix[i] != null) {
          lo = Math.min(lo, ix[i] / k);
          hi = Math.max(hi, ix[i] / k);
        }
      }
      var pad = (hi - lo) * 0.06 || hi * 0.05;
      return { first: first, y: [lo - pad, hi + pad], idx: [(lo - pad) * k, (hi + pad) * k] };
    }

    function fitScales(u) {
      var r = indexRanges(u.scales.x.min, u.scales.x.max);
      if (!r) return;
      base.i = r.first;
      u.setScale("y", { min: r.y[0], max: r.y[1] });
      u.setScale("idx", { min: r.idx[0], max: r.idx[1] });
      showLegend(shown);
    }

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

    var priceData = [x].concat(series);
    if (ix) {
      var initial = indexRanges(x[start], x[x.length - 1]) || { first: start, y: [0, 1], idx: [0, 1] };
      base.i = initial.first;
      priceOpts.scales.y = { auto: false, min: initial.y[0], max: initial.y[1] };
      priceOpts.scales.idx = { auto: false, min: initial.idx[0], max: initial.idx[1] };
      priceOpts.axes.push({
        scale: "idx",
        side: 1,
        size: 70,
        stroke: INDEX_COLOR,
        grid: { show: false },
        ticks: { stroke: grid, width: 1 },
        values: function (u, vals) { return vals.map(fmt); },
      });
      priceOpts.series.push({ label: indexName, scale: "idx", stroke: INDEX_COLOR, width: 1.5 });
      // x 범위가 바뀔 때(확대/이동) 축 범위를 다시 맞춘다.
      priceOpts.hooks.setScale = [function (u, key) { if (key === "x") fitScales(u); }];
      priceData.push(ix);
      // 가격 차트의 오른쪽 축 폭만큼 거래량 차트도 비워 두 차트의 가로 눈금을 맞춘다.
      volumeOpts.padding = [null, 70, null, null];
    }

    statusEl.remove();
    new uPlot(priceOpts, priceData, priceEl);
    new uPlot(volumeOpts, [x, data.v], volumeEl);
    showLegend(x.length - 1);
  }

  QPChart.mount(".price-chart", load);
})();
