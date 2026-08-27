# Quant Publisher 개발 규칙

## 1. 기본 원칙

- 작은 변경을 선호한다.
- 요구사항을 먼저 구현한다.
- 추상화는 실제 중복이 확인된 후 만든다.
- 미래의 요구사항을 위한 과도한 설계를 하지 않는다.
- 기존 동작을 깨는 변경은 명시적으로 확인한다.

## 2. Python

- Python 3.12+ 범위의 문법을 사용한다.
- 타입 힌트를 작성한다.
- `ruff`와 같은 정적 검사를 사용할 수 있으나 도구 추가는 실제 필요 시 결정한다.
- 가상환경과 의존성 관리는 `uv`를 사용한다.
- 전역 상태를 최소화한다.

## 3. 함수

- 하나의 함수는 하나의 명확한 책임을 가진다.
- 일반적으로 50줄을 넘기지 않는다.
- 긴 함수는 단계별 private 함수로 분리한다.
- 입력과 반환 타입을 명시한다.
- 부작용이 있는 함수는 이름으로 드러나게 한다.

## 4. 클래스

클래스가 단순히 함수 묶음 역할만 한다면 만들지 않는다.

클래스 사용이 적합한 경우:
- Repository
- 외부 데이터 Provider
- 설정이 필요한 서비스
- 상태를 유지해야 하는 명확한 객체

## 5. 이름

- 변수/함수: snake_case
- 클래스: PascalCase
- 상수: UPPER_SNAKE_CASE
- 파일: snake_case
- DB 테이블: snake_case
- DB 컬럼: snake_case

종목코드와 티커는 명시적인 이름을 사용한다.

예:
- `stock_code`
- `ticker`
- `trade_date`

## 6. 예외 처리

나쁜 예:

```python
try:
    ...
except Exception:
    pass
```

원칙:
- 예상 가능한 오류는 구체적으로 처리한다.
- 복구할 수 없는 오류는 기록 후 상위로 전달한다.
- 오류를 숨기지 않는다.
- 네트워크 오류와 데이터 검증 오류를 구분한다.

## 7. Logging

`print()`를 운영 로직의 로그로 사용하지 않는다.

로그에는 최소한 다음을 포함할 수 있다.

- 실행 시작
- 데이터 소스
- 대상
- 처리 건수
- 성공/실패
- 예외
- 소요 시간

민감한 API Key는 절대 로그에 남기지 않는다.

## 8. 설정

API Key, 경로, 환경별 설정은 코드에 하드코딩하지 않는다.

예:

```text
.env
환경변수
config/settings.py
```

`.env`는 Git에 커밋하지 않는다.

## 9. DB

- Connection 생성과 종료를 명확히 한다.
- SQL은 Repository에 모은다.
- transaction 경계를 명확히 한다.
- 날짜는 일관된 포맷을 사용한다.
- 금액과 비율의 단위를 명확히 한다.
- 중복 저장을 방지한다.

## 10. 데이터 검증

외부 데이터는 신뢰하지 않는다.

검증 대상:
- 필수 필드
- 날짜
- 종목코드
- 숫자 타입
- 결측치
- 비정상 범위
- 중복

검증 실패 데이터를 정상 데이터처럼 저장하지 않는다.

## 11. 테스트

핵심 계산 함수는 pytest로 테스트한다.

우선순위:
1. 분석 계산
2. 데이터 변환
3. Repository
4. 크롤러 파싱
5. 리포트 생성

외부 API 자체를 테스트하기보다 mock 또는 fixture를 사용한다.

## 12. 테스트 명칭

예:

```text
test_calculate_roe_returns_none_when_equity_is_zero
test_security_repository_upserts_existing_code
test_report_contains_stock_name
```

## 13. Git

작은 논리 단위로 commit한다.

예:

```text
feat: add security repository
test: add security repository tests
fix: handle empty financial data
docs: update setup guide
```

Task 하나가 끝났을 때 commit 가능한 상태를 만든다.

## 14. 의존성

새 패키지는 다음 조건 중 하나를 만족할 때만 추가한다.

- 표준 라이브러리로 구현하기 어려움
- 코드 복잡도를 크게 줄임
- 프로젝트 핵심 기능에 필요함

패키지를 추가할 때 이유를 문서 또는 commit message에 남긴다.

## 15. 웹

Hugo 템플릿과 Python 코드를 섞지 않는다.

Python:
- 데이터
- 계산
- Markdown/content 생성

Hugo:
- layout
- navigation
- rendering

## 16. 보안

Git에 커밋 금지:
- API Key
- Access Token
- 개인 비밀번호
- 쿠키
- 인증서 private key

공개 웹사이트에는 개인정보와 비공개 투자 데이터가 포함되지 않도록 한다.

## 17. Claude Code 작업 규칙

Claude는:
- Task에 없는 기능을 추가하지 않는다.
- 기존 코드를 읽지 않고 대규모 수정하지 않는다.
- 테스트 실패를 무시하지 않는다.
- 실패 원인을 임시 workaround로 숨기지 않는다.
- 필요 이상으로 파일을 만들지 않는다.
- 작업 후 변경 파일을 보고한다.

## 18. 완료 기준

다음 모두 만족해야 한다.

- 요구사항 구현
- 관련 테스트 통과
- 기존 테스트에 회귀 없음
- 오류 처리 확인
- 로그 확인
- 문서 업데이트 필요 여부 확인
- Task Acceptance Criteria 충족
