# Task 016 - 리포트 출력 안정화 (불필요한 파일 변경 제거)

## 목표

데이터가 바뀌지 않은 종목의 content 파일이 매일 바뀌는 문제(`docs/OPERATIONS.md` 5절 #1)를
해결한다. 종목 페이지 고도화(Task 017~021)에서 차트 JSON 등 생성 파일이 늘어나도
git 변경과 커밋이 데이터 변화만 반영하도록 하는 선행 작업이다.

## 선행 조건

Task 015가 완료되고 테스트가 통과한 상태여야 한다.

## 작업 범위

`src/quantpublisher/report/`, `src/quantpublisher/automation/daily_update.py`,
`website/layouts/stocks/single.html`, `tests/`

## 구현 내용

- `StockReport.generated_at`(실행 시각)을 `data_date`(해당 종목의 최신 거래일, `YYYY-MM-DD`)로 바꾼다.
  가격 데이터가 없는 종목은 `None`이며, front matter의 `date`를 생략하고 본문에 `N/A`로 표시한다.
- `daily_update`는 `PriceRepository.get_latest_trade_dates()`를 한 번 호출해 종목별 기준일을 넘긴다.
- `write_stock_report_markdown`은 기존 파일 내용이 렌더링 결과와 같으면 다시 쓰지 않는다.
- Hugo 레이아웃의 "생성 시각"을 "데이터 기준일"로 바꾼다.

## Acceptance Criteria

- 같은 데이터로 `daily_update`를 다시 실행하면 어떤 content 파일도 다시 쓰이지 않는다 (mtime 불변).
- 가격 데이터가 있는 종목의 `date`와 본문 "데이터 기준일"은 최신 거래일이다.
- 가격 데이터가 없는 종목은 `date`가 없고 "데이터 기준일: N/A"로 표시된다.
- `uv run pytest` 전체 통과.

## 확인 결과 (2026-10-11)

- 실제 DB 2,831개 종목을 scratchpad에 두 번 렌더링해 재실행 시 다시 쓴 파일이 0개임을 확인했다.
- 첫 실행에서는 템플릿 형식이 바뀌어 기존 content 파일 대부분이 한 번 변경된다. 이후부터는 데이터가 바뀐 종목만 변경된다.

## 남은 TODO

- 실제 `website/content`는 아직 재생성하지 않았다. `daily_update`를 실행하면 한 번 대량 변경이 생긴다.
- 가격 데이터는 `market_data_import`를 수동 실행해야 갱신되므로, 가져오기를 돌리기 전까지 기준일은 그대로다.

## 다음 Task

Task 017 - 가격 차트
