# Task 017 - 가격 차트

## 목표

종목 페이지에 `prices_daily`의 일봉으로 만든 가격 차트(종가, 이동평균 20/60/120, 거래량)를 추가한다.
`docs/PROJECT_SPEC.md`의 "웹 기능은 Hugo와 정적 JavaScript로 먼저 해결" 원칙을 따른다.

## 선행 조건

Task 016 완료.

## 구현 내용

- `report/chart_data.py`: 일봉을 열 방향 compact JSON(`code`, `t`=epoch 일수, `c`=종가, `v`=거래량)으로 바꾸고
  `website/static/charts/prices/<코드>.json`에 쓴다. 내용이 같으면 다시 쓰지 않는다.
  경로에 `data`를 쓰지 않은 이유는 `.gitignore`의 `data/` 패턴이 `website/static/data/`까지 무시하기 때문이다.
- `PriceRepository.list_recent_by_code(code, limit)`: 종목별 최근 N개 일봉만 조회한다.
- 저장 범위: 최근 370거래일(`CHART_MAX_ROWS`). 첫 화면은 최근 250거래일이고 드래그로 더 볼 수 있다.
  측정 결과 종목당 평균 6.5KB, 전체 2,614개 약 17MB이다. 3년치 일봉은 종목당 약 20KB(전체 약 50MB)라서,
  가져오기 때마다 모든 파일이 바뀌는 git 이력 증가를 고려해 줄였다.
- 이동평균은 JS에서 계산한다 (`website/static/js/pricechart.js`).
- uPlot 1.6.31(MIT)을 `website/static/vendor/uplot/`에 포함한다 (CDN 의존 없음, LICENSE 포함).
- Hugo shortcode `website/layouts/shortcodes/pricechart.html`. 템플릿은 차트 JSON이 있는 종목에만
  `{{< pricechart code="..." >}}`를 넣는다 (`StockReport.has_price_chart`). `hugo.yaml`의 `unsafe: false`는 그대로다.
- `daily_update`는 content 경로 기준(`../../static/charts`)으로 차트를 생성하며 `chart_dir`(루트)로 바꿀 수 있다. Task 018부터 루트 아래 `prices/`, `financials/`를 쓴다.
- `scripts/daily_update.sh`가 `website/static/charts`도 commit 대상에 포함한다.

## 확인 결과 (2026-10-11)

- `uv run pytest` 153개 통과.
- `daily_update` 재실행 시 변경 파일 0개. 차트 JSON 2,614개, 차트 없는 종목 217개는 content 변경 없음.
- `hugo --gc --minify` 빌드 성공 (사이트 약 53MB). 차트 없는 종목 페이지에는 차트 마크업이 없다.
- 브라우저(Chrome)에서 005930 페이지의 차트 2개 렌더링과 범례 값(종가 263,500, 거래량 19,694,850, MA20 267,325)이
  DB와 일치함을 확인했다. 브라우저 탭이 화면에 보이지 않는 상태(`hidden`)라 스크린샷은 얻지 못했다.

## 남은 TODO

- 시각 확인(레이아웃, 색상, 모바일 폭, 마우스 호버/드래그 확대)은 사람이 `hugo server`로 한 번 봐야 한다.
- 다크 모드는 없다 (사이트 CSS가 라이트 전용).
- 가격 가져오기(`market_data_import`)가 수동이라 차트도 그때까지 갱신되지 않는다 (OPERATIONS.md 5절 #3).

## 다음 Task

Task 018 - 재무 시계열 + 주요실적 자동 요약
