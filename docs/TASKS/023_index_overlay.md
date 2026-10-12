# Task 023 - 가격 차트에 시장 대표지수 겹쳐 표시

## 목표

종목 가격 차트에 소속 시장의 대표지수(KOSPI, KOSDAQ)를 겹쳐 그려 시장 대비 성과를 한눈에 본다.
왼쪽 y축은 종목 원래 가격, 오른쪽 y축은 지수 포인트이고, 보이는 구간의 첫 거래일에서 두 선이 같은 점에서
출발하도록 맞춘다(정규화).

## 구현 내용

- `crawler/index_chart.py`: FinanceDataReader(`KS11`, `KQ11`)로 지수 일봉을 받아
  `website/static/charts/index/<KOSPI|KOSDAQ>.json`으로 저장한다 (`{"code","t","c"}`, 최근 370거래일).
  시장당 파일 하나를 모든 종목 페이지가 공유한다. DB에는 저장하지 않는다.
  한 지수가 실패하면 그 파일은 그대로 두고 경고만 남긴다.
  단독 실행: `uv run python -m quantpublisher.crawler.index_chart`. `daily_update`도 끝에 같이 실행한다
  (실패해도 종료 코드에 영향 없음).
- `report/chart_data.py`: `INDEX_SYMBOLS`, `build_index_chart_data`, `write_index_chart_json`.
- 템플릿/shortcode: KOSPI·KOSDAQ 종목은 `{{< pricechart code="..." market="KOSPI" >}}`로 만든다.
  KONEX는 `market` 없이 기존과 같다.
- `pricechart.js`: `data-index-src`가 있으면 지수를 불러와 종목의 거래일에 맞추고(지수에 빠진 날은 직전 값,
  지수 시작 전과 마지막 날 이후는 비움), 오른쪽 축 범위를 `왼쪽 범위 x (기준일 지수 / 기준일 종가)`로 둔다.
  확대/이동으로 x 범위가 바뀌면 기준일과 두 축 범위를 다시 계산한다.
  범례에 지수 값과, 종가·지수의 기준일 대비 변화율(%)을 같이 보여준다.
  지수를 못 불러오면 지수 없이 기존 차트로 그린다. 거래량 차트는 가격 차트와 가로 눈금이 맞도록
  오른쪽 여백을 둔다.

## 확인 결과 (2026-10-12)

- `uv run pytest` 248개 통과 (지수 JSON 변환·저장, 일부 실패 시 계속, shortcode의 market 전달).
- 삼성전자(005930) 페이지에서 종목선과 KOSPI선이 같은 점에서 출발하고, 좌우 축이 각각 원 단위 가격과 지수
  포인트로 표시되며, 커서 위치에서 범례에 값과 변화율이 갱신되는 것을 브라우저로 확인했다.
  가격·거래량 차트의 플롯 폭이 같다.
- 종목 페이지 2,614개의 pricechart 줄이 바뀌었다 (KOSDAQ 1,699개, KOSPI 915개).

## 알려진 제한

- FinanceDataReader의 지수 일봉이 종목 시세보다 며칠 늦을 수 있다. 이 경우 지수선은 마지막 지수 날짜에서 끝난다.
- 지수는 종가지수만 쓰고 배당·분할 보정은 없다. 종목 가격도 원 종가 기준이다.
- 지수 파일은 `daily_update`나 위 명령을 실행해야 갱신된다.
