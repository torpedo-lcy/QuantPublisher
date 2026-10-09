# Task 015 - 지표 계산 연결과 리포트 반영

## 목표

Task 013/014에서 저장한 가격·재무 데이터를 `analysis/metrics.py`의 계산 함수와
`daily_update` 파이프라인에 실제로 연결해, 종목별 페이지에 더 이상 전체 N/A가 아닌
실제 지표가 표시되도록 한다.

## 선행 조건

Task 013(가격 데이터), Task 014(재무/밸류에이션 데이터)가 완료되고 테스트가 통과한
상태여야 한다.

## 작업 범위

`src/quantpublisher/report/`, `src/quantpublisher/automation/`, `tests/`

## 수정 금지 원칙

현재 Task와 직접 관련 없는 영역은 수정하지 않는다.
구조 개선이 필요하더라도 먼저 이유를 보고하고 최소 변경으로 처리한다.

`analysis/metrics.py`의 계산 함수 자체(Task 005에서 구현, 테스트 완료)는 수정하지 않는다.
이 Task는 "연결"만 담당한다.

## 구현 요구사항

- 기존 프로젝트 규칙을 따른다.
- 타입 힌트를 사용한다.
- 핵심 로직에 테스트를 작성한다.
- 예외 상황을 명시적으로 처리한다.
- 로그가 필요한 경우 logging을 사용한다.
- 비밀값을 코드나 테스트 fixture에 넣지 않는다.

### 연결 범위

`daily_update`가 각 종목의 `StockMetrics`를 채울 때 다음을 조회해 계산 함수에 전달한다.

| 지표 | 산출 방식 |
|---|---|
| ROE, ROA | `financial_statements`(최신 연간)의 net_income/equity/assets → `calculate_roe`, `calculate_roa` |
| 영업이익률, 순이익률 | 같은 행의 operating_income/net_income/sales → `calculate_operating_margin`, `calculate_net_margin` |
| 부채비율 | liabilities/equity → `calculate_debt_ratio` |
| 매출성장률 | 연간 2개 연도의 sales → `calculate_revenue_growth_rate` (전년도 데이터가 없으면 None) |
| PER, PBR | `financial_metrics`(최신 월)의 per/pbr을 그대로 사용 (재계산하지 않음) |
| EPS, BPS | `financial_metrics.close_price / per`, `close_price / pbr` (per/pbr이 없거나 0이면 None) |
| 배당수익률 | 데이터 없음. 항상 None → 페이지에 N/A |

### 페이지 표시 규칙

- 지표 값과 함께 **기준 연도/월**을 표시한다 (예: "ROE 12.3% (2025년 연간 기준)").
  값만 보여주고 기준 시점을 숨기지 않는다.
- `is_consolidated` 값에 따라 "연결" / "별도" 기준임을 표시한다.
- 계산에 쓸 데이터가 없는 지표는 기존처럼 "N/A"로 표시하고, 이유를 구분하지 않아도 된다
  (예: 재무 데이터 자체가 없음 vs. net_income 미공시로 None됨 — 둘 다 N/A로 충분하다).
- `report/models.py`의 `StockReport`/`StockMetrics` 구조는 가능하면 변경하지 않는다.
  기준 연도/월, 연결 여부를 표시해야 한다면 필드 추가 범위와 이유를 먼저 보고한다.

### 매출성장률 계산 시 주의

전년도 연간 데이터가 없으면 `calculate_revenue_growth_rate`에 None을 넘겨 결과가
None이 되도록 한다. 임의로 추정하지 않는다.

## Acceptance Criteria

fixture 기반으로 다음이 테스트되어야 한다.

- 가격·재무 데이터가 모두 있는 샘플 종목의 페이지에 ROE/PER 등 실제 값이 표시된다.
- 재무 데이터가 없는 종목은 해당 지표가 N/A로 표시되고, 파이프라인이 오류 없이 끝난다.
- 전년도 데이터가 없으면 매출성장률이 N/A로 표시된다 (추정값을 만들지 않는다).
- 지표 옆에 기준 연도/월이 함께 표시된다.

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

- 이 Task에서 다음 단계의 기능까지 선행 구현하지 않는다. 백테스트 연결은 별도 Task로 다룬다.
- `analysis/metrics.py`의 계산 함수를 수정하지 않는다. 입력 데이터를 조회해 전달하는
  연결 코드만 작성한다.
