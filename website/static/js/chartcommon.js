// 차트 공통 헬퍼 (가격/재무 차트가 함께 쓴다). window.QPChart로 노출한다.
(function () {
  "use strict";

  function fmt(v) {
    return v == null ? "-" : v.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }

  // 억원 단위 값을 읽기 쉽게 (1조 = 10,000억).
  function fmtEok(v) {
    if (v == null) return "-";
    if (Math.abs(v) >= 10000) return (v / 10000).toLocaleString("ko-KR", { maximumFractionDigits: 2 }) + "조";
    return v.toLocaleString("ko-KR", { maximumFractionDigits: 0 }) + "억";
  }

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  // 범례를 만든다: 맨 앞 머리글(날짜/연도) + [색 표시, 이름, 값] 항목들.
  // items: [{label, color, get(i), format?}]. 반환값 show(i, headText)로 값을 갱신한다.
  function buildLegend(legendEl, items) {
    legendEl.textContent = "";
    var headEl = document.createElement("span");
    headEl.className = "chart-legend-head";
    legendEl.appendChild(headEl);
    var valueEls = items.map(function (item) {
      var wrap = document.createElement("span");
      wrap.className = "chart-legend-item";
      var swatch = document.createElement("span");
      swatch.className = "chart-legend-swatch";
      swatch.style.background = item.color;
      var valueEl = document.createElement("span");
      wrap.appendChild(swatch);
      wrap.appendChild(document.createTextNode(item.label + " "));
      wrap.appendChild(valueEl);
      legendEl.appendChild(wrap);
      return valueEl;
    });
    return function show(i, headText) {
      headEl.textContent = headText;
      items.forEach(function (item, k) {
        valueEls[k].textContent = (item.format || fmt)(item.get(i));
      });
    };
  }

  // 컨테이너의 data-src JSON을 읽어 render(el, data)를 호출한다. 실패하면 상태 문구에 이유를 적는다.
  function mount(selector, render) {
    document.addEventListener("DOMContentLoaded", function () {
      if (typeof uPlot === "undefined") return;
      document.querySelectorAll(selector).forEach(function (el) {
        var statusEl = el.querySelector(".chart-status");
        fetch(el.getAttribute("data-src"))
          .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
          })
          .then(function (data) { return render(el, data); })
          .catch(function (err) {
            statusEl.textContent = "차트 데이터를 불러오지 못했습니다 (" + err.message + ").";
          });
      });
    });
  }

  window.QPChart = { fmt: fmt, fmtEok: fmtEok, cssVar: cssVar, buildLegend: buildLegend, mount: mount };
})();
