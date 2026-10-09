# Task 014 - 재무/밸류에이션 데이터 가져오기

## 목표

외부 Mac mini의 `quant.db`에서 `financial_data`(연간 재무제표)와
`market_data`(월별 밸류에이션)를 가져와 QuantPublisher의 자체 테이블에 저장한다.

## 선행 조건

이전 Task가 완료되고 테스트가 통과한 상태여야 한다. Task 013에서 `quant.db` 접속 방식과
`securities.corp_code`가 이미 구현되어 있어야 한다.

## 작업 범위

`src/quantpublisher/crawler/`, `src/quantpublisher/database/`, `tests/`

## 수정 금지 원칙

현재 Task와 직접 관련 없는 영역은 수정하지 않는다.
구조 개선이 필요하더라도 먼저 이유를 보고하고 최소 변경으로 처리한다.

지표 계산(`analysis/`)과 리포트 연결(`report/`, `automation/daily_update.py`)은
이 Task의 범위가 아니다. 데이터를 저장하는 것까지만 한다.

## 구현 요구사항

- 기존 프로젝트 규칙을 따른다.
- 타입 힌트를 사용한다.
- 핵심 로직에 테스트를 작성한다.
- 예외 상황을 명시적으로 처리한다.
- 로그가 필요한 경우 logging을 사용한다.
- 외부 API를 사용하는 경우 fixture/mock을 이용해 반복 가능한 테스트를 만든다.
- 비밀값을 코드나 테스트 fixture에 넣지 않는다.

### 스키마

```sql
CREATE TABLE IF NOT EXISTS financial_statements (
    stock_code       TEXT NOT NULL,
    year             INTEGER NOT NULL,
    report_type      TEXT NOT NULL,   -- '11011'=연간, '11012'=반기, '11013'=1분기, '11014'=3분기
    assets           REAL,
    liabilities      REAL,
    equity           REAL,
    current_assets   REAL,
    current_liab     REAL,
    sales            REAL,
    gross_profit     REAL,
    operating_income REAL,
    net_income       REAL,
    is_consolidated  INTEGER,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, year, report_type),
    FOREIGN KEY (stock_code) REFERENCES securities(stock_code)
);

CREATE TABLE IF NOT EXISTS financial_metrics (
    stock_code   TEXT NOT NULL,
    year_month   TEXT NOT NULL,       -- YYYY-MM
    trade_date   TEXT,
    close_price  REAL,
    market_cap   REAL,
    shares_out   REAL,
    per          REAL,
    pbr          REAL,
    psr          REAL,
    pcr          REAL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, year_month),
    FOREIGN KEY (stock_code) REFERENCES securities(stock_code)
);
```

`quant_metrics`는 가져오지 않는다. 이 프로젝트의 `analysis/metrics.py` 계산 함수로 직접
계산하고, `quant_metrics`는 비교·검증 용도로만 수동 참고한다 (DB에 적재하지 않는다).

### 가져오기 흐름

```text
quant.db (.backup 스냅샷, Task 013에서 이미 구현된 복사 경로 재사용)
  → financial_data 파싱 + 검증 → financial_statements upsert
  → market_data 파싱 + 검증    → financial_metrics upsert
```

### 데이터 처리 규칙 (중요)

- **`financial_data.eps`는 가져오지 않는다.** 소스 데이터에서 상시 0으로 확인되어 신뢰할 수 없다.
  EPS/BPS는 이후 Task(015)에서 `financial_metrics`의 `close_price`, `per`, `pbr`로부터
  역산한다 (`eps = close_price / per`, `bps = close_price / pbr`). 이 Task는 저장까지만 하고
  역산 로직은 만들지 않는다.
- **`net_income == 0.0`은 "미공시"로 간주해 `NULL`로 저장한다.** DART 잠정실적 공시가
  순이익 없이 먼저 올라오는 경우가 많아, 0을 그대로 저장하면 이후 ROE 등이 0%로
  잘못 계산된다. `sales`, `operating_income` 등 다른 값이 있는데 `net_income`만 0이면
  특히 이 경우에 해당한다. 테스트로 이 변환을 검증한다.
- **`cf_operating`, `cf_investing`, `cf_financing`, `sales_yoy`, `op_income_yoy`,
  `net_income_yoy`는 가져오지 않는다.** 소스에서 비어 있는 경우가 많고, 성장률은
  이후 Task에서 연간(`report_type='11011'`) 2개 연도를 비교해 직접 계산한다.
- **최초 범위는 연간(`report_type='11011'`)만 가져온다.** 분기/반기 값은 누적 여부가
  불명확해 연간 지표와 바로 비교할 수 없다. 분기 데이터 활용은 별도 Task로 분리한다.
- 날짜·숫자 변환에서 암묵적 변환을 피한다. 변환 규칙(특히 `net_income` 0 처리)은
  코드 주석과 테스트 이름에 명시적으로 드러낸다.

### 검증

- `stock_code`: `securities`에 존재해야 한다. 없으면 건너뛰고 로그에 남긴다.
- `year`: 합리적인 범위(예: 2000 이상, 현재 연도 이하)인지 확인한다.
- `report_type`: `'11011'`만 허용한다 (이 Task 범위).
- 숫자 필드: 타입과 결측치를 확인한다. 전부 `NULL`인 행은 저장하지 않는다.
- 중복 저장 방지: `(stock_code, year, report_type)`, `(stock_code, year_month)` 기준 upsert.

## Acceptance Criteria

fixture 기반으로 다음이 테스트되어야 한다.

- 연간 재무제표가 `financial_statements`에 upsert된다.
- `net_income == 0.0`인 행이 `NULL`로 저장된다 (0으로 저장되지 않는다).
- 월별 밸류에이션이 `financial_metrics`에 upsert된다.
- `securities`에 없는 종목코드의 데이터는 저장되지 않고 로그에 남는다.
- 재실행해도 데이터가 중복되지 않는다.

추가 Acceptance Criteria:
- 기존 테스트가 깨지지 않는다.
- Task 완료 후 로컬에서 기능을 직접 실행할 수 있다.
- 변경된 파일 목록이 명확하다.

## Definition of Done

- [ ] 요구사항 구현
- [ ] 관련 테스트 작성
- [ ] pytest 통과
- [ ] 기존 기능 회귀 확인
- [ ] 오류 처리 확인
- [ ] 로그 또는 실행 결과 확인
- [ ] 필요한 문서 업데이트
- [ ] 변경 파일 검토
- [ ] Git commit 가능한 상태

## Claude Code 작업 절차

1. 프로젝트의 `CLAUDE.md`를 읽는다.
2. `docs/PROJECT_SPEC.md`를 읽는다.
3. `docs/ARCHITECTURE.md`를 읽는다.
4. `docs/DEVELOPMENT_RULE.md`를 읽는다.
5. 현재 코드와 테스트를 먼저 확인한다.
6. 필요한 최소 변경을 구현한다.
7. 테스트를 실행한다.
8. 실패하면 원인을 수정한 뒤 다시 실행한다.
9. 완료 조건을 확인한다.
10. 결과를 요약한다.

## 완료 보고 형식

```text
구현 내용:
- ...

변경 파일:
- ...

테스트:
- ...

Acceptance Criteria:
- ...

남은 TODO:
- ...

다음 Task:
- ...
```

## 주의

- 이 Task에서 다음 단계의 기능까지 선행 구현하지 않는다. `analysis/`, `report/`,
  `automation/daily_update.py`를 수정하지 않는다.
- 분기/반기(`11012`, `11013`, `11014`) 데이터는 이 Task에서 다루지 않는다.
- `quant_metrics`를 그대로 복사해 저장하지 않는다. 비교·검증 용도로만 수동 참고한다.
