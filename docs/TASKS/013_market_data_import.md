# Task 013 - 가격 데이터 가져오기

## 목표

로컬 네트워크의 다른 Mac mini에 있는 종목별 가격 SQLite DB(`stock-price/<종목코드>.db`)의
`daily` 테이블을 가져와 QuantPublisher의 `prices_daily` 테이블에 저장하는 Collector를 구현한다.
동시에 `securities` 테이블에 `corp_code` 열을 추가하고, 외부 `quant.db`의 `stock_master`에서
값을 채운다.

## 선행 조건

이전 Task가 완료되고 테스트가 통과한 상태여야 한다.

Task를 시작하기 전에 다음을 Mac mini에서 확인한다.

- 외부 Mac mini에 SSH로 접속 가능 (원격 로그인 활성화).
- `stock-price/<종목코드>.db`의 `daily` 테이블 스키마: `Time TEXT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL`.
- `quant.db`의 `stock_master` 테이블: `stock_code, stock_name, corp_code, market, updated_at`.
- `stock-price`는 매일 오후 4시 20분경 갱신되고, `quant.db`는 월 1회 갱신된다.

## 작업 범위

`src/quantpublisher/crawler/`, `src/quantpublisher/database/`, `scripts/`, `tests/`

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
CREATE TABLE IF NOT EXISTS prices_daily (
    stock_code  TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, trade_date),
    FOREIGN KEY (stock_code) REFERENCES securities(stock_code)
);
```

`securities`에 `corp_code TEXT` 열을 추가한다 (nullable, DART 고유번호 8자리).
기존 데이터와 테스트를 깨뜨리지 않는 방식(예: `ALTER TABLE ... ADD COLUMN`)으로 추가한다.

### 가져오기 흐름

```text
외부 Mac (SSH)
  → stock-price/*.db 의 daily 테이블만 추출
  → 중간 파일 (PSV/CSV)
  → rsync로 이 Mac에 복사
  → 파싱 + 검증
  → prices_daily upsert

quant.db
  → .backup 스냅샷
  → rsync로 이 Mac에 복사
  → stock_master 파싱
  → securities.corp_code upsert
```

- 외부 Mac에는 아무것도 설치하거나 수정하지 않는다. 읽기 전용 명령만 SSH로 실행한다.
- 최초 실행은 전체 종목의 `daily` 전체를 가져온다 (최초 백필).
- 이후 실행은 종목별로 `prices_daily`에 저장된 최신 `trade_date` 이후 행만 가져온다 (증분).
  - 증분 조건: 외부 `Time > 이 DB에 저장된 해당 stock_code의 MAX(trade_date)`.
  - 해당 종목이 `prices_daily`에 전혀 없으면 전체 백필로 처리한다.
- `quant.db`는 `.backup` 명령으로 스냅샷을 만든 뒤 복사한다 (쓰는 도중에도 안전하게).
- 접속 정보(호스트, 사용자, 원격 경로)는 하드코딩하지 않고 `config/settings.py` 또는 환경변수로 뺀다.

### 검증

- `trade_date`: `YYYY-MM-DD` 형식인지 확인한다.
- `stock_code`: `securities`에 존재하는 종목코드인지 확인한다. 존재하지 않으면 해당 행은 건너뛰고 로그에 남긴다 (조용히 버리지 않는다).
- 가격/거래량: 숫자 타입이고 `None`이 아닌지 확인한다. 음수 가격처럼 비정상 범위는 건너뛰고 기록한다.
- 중복 저장 방지: `(stock_code, trade_date)` 기준 upsert.

### 실패 처리

- SSH 접속 실패, 원격 명령 실패, 파일 전송 실패는 구체적으로 구분해서 처리하고 예외를 상위로 전달한다 (조용히 넘어가지 않는다).
- 한 종목의 가져오기가 실패해도 다른 종목 처리를 중단하지 않는다. 단, 전체 실행 결과에는 실패한 종목 수를 포함해 보고하고, 실패가 있었다는 사실 자체는 숨기지 않는다.
- 외부 Mac에 접속할 수 없으면 (예: 꺼져 있음) 전체를 실패로 처리하고 명확한 오류 메시지를 남긴다. 기존 `prices_daily` 데이터는 건드리지 않는다.

## Acceptance Criteria

fixture 기반으로 다음이 테스트되어야 한다.

- 최초 실행 시 가격 데이터가 `prices_daily`에 upsert된다.
- 재실행 시 이미 저장된 날짜는 중복 저장되지 않고, 새 날짜만 추가된다.
- `securities`에 없는 종목코드의 가격 데이터는 저장되지 않고 로그에 남는다.
- `securities.corp_code`가 `quant.db`의 `stock_master`로부터 채워진다.
- 외부 Mac 접속 실패 시 기존 `prices_daily` 데이터가 변경되지 않는다.

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

- 이 Task에서 다음 단계의 기능까지 선행 구현하지 않는다. `analysis/`, `report/`, `automation/daily_update.py`를 수정하지 않는다.
- `minute` 테이블은 가져오지 않는다.
- 외부 DB의 스키마나 데이터를 수정하지 않는다. 항상 읽기 전용으로 접근한다.
