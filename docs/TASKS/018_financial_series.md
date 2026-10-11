# Task 018 - 재무 시계열과 주요 실적 요약

## 목표

종목 페이지에 연간 재무 시계열(차트와 표)과, 재무 데이터로 자동 생성한 "주요 실적 요약"을 추가한다.
외부 호출 없이 DB의 `financial_statements`만 사용한다.

## 선행 조건

Task 017 완료.

## 구현 내용

- `analysis/performance.py`(새 파일): `classify_change(current, previous)`가 증가/감소/동일/흑자전환/적자전환/
  적자 축소/적자 확대로 분류하는 순수 함수다. 변화율은 전기·당기가 모두 양수일 때만 계산한다
  (적자가 섞이면 비율이 오해를 부르기 때문). 기존 `metrics.py`는 수정하지 않았다.
- `report/models.py`: `FinancialYear`(연도, 연결/별도, 매출액, 영업이익, 순이익, 영업이익률, ROE),
  `StockReport.financial_history`, `has_financial_chart`.
- `automation/stock_metrics.py`: `build_financial_history`(순수 함수, 최근 8개 연도, 값이 전혀 없는 해는 제외),
  `load_financial_history`.
- `report/markdown.py`: 원 단위 금액을 `333.61조원` / `3,000억원` 형식으로 바꾸는 `fmt_won`과
  요약 문장 생성 `performance_lines`. 최신 연도를 직전 연도와 비교하되, 직전 연도가 없거나
  연결/별도 기준이 다르면 비교하지 않고 그 사실을 적는다.
- 템플릿에 "재무 시계열"(차트, 연도별 표) 과 "주요 실적 요약" 섹션 추가. 재무 데이터가 없는 종목은 섹션 전체를 생략한다.
- `report/chart_data.py`: 재무 차트 JSON(`website/static/charts/financials/<코드>.json`, 억원 정수, 결측은 null).
  2개 연도 이상일 때만 만든다.
- 프런트엔드: 공통 헬퍼 `chartcommon.js`(포맷, 범례, 로딩)와 partial `chart-base-assets.html`로
  uPlot 자산을 한 번만 로드하게 정리하고, `financialchart.js` / shortcode `financialchart`를 추가했다.
  가격 차트도 같은 범례 헬퍼를 쓰며, 모든 차트에 색 표시가 있는 범례가 있다.

## 확인 결과 (2026-10-11)

- `uv run pytest` 176개 통과 (분류 규칙, 시계열 조립, 금액 형식, 비교 불가 처리, 파이프라인 테스트 추가).
- 실제 DB: 재무 시계열이 있는 종목 2,544개, 재무 차트 JSON 2,486개(연도 1개뿐인 58개 종목은 표와 요약만 있음).
  JSON 용량은 약 9.7MB(`du` 기준).
- 삼성전자(005930) 2025년 매출 333.61조원, 전년 대비 +10.88%가 DB 값과 일치한다.
- Chrome에서 005930 페이지의 차트 3개(가격, 거래량, 재무)가 렌더링되고 범례 색과 값이 표시됨을 확인했다.
  uPlot과 공통 스크립트는 페이지당 한 번만 로드된다. (탭이 hidden이라 스크린샷은 얻지 못했다.)

## 알려진 제한

- 원천 데이터의 결측(매출액 약 17%, 금융업 등 포함)은 N/A로 표시된다. 예: 삼성전자 2023년 매출액이 원천에 없어
  표에는 N/A, 차트에는 선이 끊긴다. 추정으로 채우지 않는다.
- 593개 종목은 연도에 따라 연결/별도가 섞여 있다. 표에 연도별 기준을 표시하고, 기준이 다른 해끼리는 증감을 계산하지 않는다
  (159개 페이지가 "비교할 수 없음").
- 연간(11011) 데이터만 있어 분기 실적은 없다.

## 남은 TODO

- 모바일 폭, 호버 동작 등 시각 확인은 사람이 `hugo server`로 한 번 봐야 한다.

## 다음 Task

Task 019 - 기업정보 수집 (업종, 연혁, 사업내용). DART API 키(`QP_DART_API_KEY`)가 필요하다.
