# Quant Publisher 아키텍처

## 1. 전체 구조

```text
                    ┌──────────────────┐
                    │ External Sources │
                    │ KRX / DART / API │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ Python Crawler   │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ SQLite Database  │
                    └────────┬─────────┘
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
          ┌──────────────┐      ┌──────────────┐
          │ Analysis     │      │ Backtest     │
          └──────┬───────┘      └──────┬───────┘
                 │                     │
                 └──────────┬──────────┘
                            ▼
                   ┌─────────────────┐
                   │ Report Generator│
                   └────────┬────────┘
                            │ Markdown
                            ▼
                   ┌─────────────────┐
                   │ Hugo            │
                   └────────┬────────┘
                            │ HTML
                            ▼
                   ┌─────────────────┐
                   │ GitHub Pages    │
                   └────────┬────────┘
                            ▼
                   ┌─────────────────┐
                   │ Cloudflare      │
                   └─────────────────┘
```

## 2. 계층

### Crawler

외부 데이터 수집만 담당한다.

금지:
- HTML 템플릿 생성
- 투자 판단
- 웹사이트 배포

### Database

SQLite 연결과 저장을 담당한다.

금지:
- 외부 API 호출
- Markdown 생성
- 분석 로직

### Analysis

저장된 데이터를 계산하고 지표를 만든다.

금지:
- 직접 크롤링
- Git push
- Hugo 실행

### Report

분석 결과를 Markdown으로 변환한다.

### Website

Hugo 템플릿과 콘텐츠를 관리한다.

### Automation

각 작업을 순서대로 호출한다.

## 3. 권장 디렉터리

```text
QuantPublisher/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .gitignore
│
├── config/
│   ├── __init__.py
│   └── settings.py
│
├── src/
│   └── quantpublisher/
│       ├── __init__.py
│       ├── crawler/
│       ├── database/
│       ├── analysis/
│       ├── report/
│       └── automation/
│
├── data/
│   ├── raw/
│   └── quantpublisher.sqlite3
│
├── reports/
│
├── website/
│   ├── archetypes/
│   ├── content/
│   ├── layouts/
│   ├── static/
│   ├── themes/
│   └── hugo.yaml
│
├── scripts/
│
├── tests/
│
├── logs/
│
└── docs/
    ├── PROJECT_SPEC.md
    ├── ARCHITECTURE.md
    ├── DEVELOPMENT_RULE.md
    └── TASKS/
```

## 4. 데이터 흐름

데이터는 다음 순서를 지킨다.

```text
Source
→ Collector
→ Validation
→ Repository
→ SQLite
→ Analysis
→ Report
→ Hugo
```

가능하면 계층을 건너뛰지 않는다.

## 5. SQLite

초기에는 단일 DB 파일을 사용한다.

```text
data/quantpublisher.sqlite3
```

개발 환경과 운영 환경을 분리해야 할 필요가 생기기 전까지는 동일한 구조를 사용한다.

### 기본 테이블 후보

- securities
- prices_daily
- financial_statements
- financial_metrics
- data_sources
- collection_runs

필요하지 않은 테이블은 미리 만들지 않는다.

## 6. Repository

SQL을 애플리케이션 전체에 흩뿌리지 않는다.

예:

```python
class SecurityRepository:
    def get_by_code(self, code: str) -> Security | None:
        ...

    def upsert(self, security: Security) -> None:
        ...
```

Repository는 데이터 접근을 담당하고 분석 의미를 결정하지 않는다.

## 7. 분석

분석 함수는 가능한 한 순수 함수에 가깝게 작성한다.

예:

```python
def calculate_roe(net_income: float, equity: float) -> float | None:
    ...
```

DB를 직접 읽는 함수와 계산 함수를 분리한다.

## 8. 리포트

리포트 생성은 템플릿 기반으로 한다.

```text
분석 결과
→ report model
→ Jinja2 template
→ Markdown
```

Markdown에는 원시 SQL을 넣지 않는다.

## 9. Hugo

Hugo는 `website/` 아래에 둔다.

Python은 Hugo 내부 템플릿을 직접 수정하지 않고, 필요한 경우 content 파일과 데이터 파일을 생성한다.

## 10. 배포

초기에는 GitHub Pages를 사용한다.

Mac mini에서:

```text
데이터 갱신
→ 리포트 생성
→ website content 갱신
→ git commit
→ git push
```

GitHub에서:

```text
push
→ GitHub Actions
→ Hugo build
→ Pages deploy
```

## 11. 자동화

macOS `launchd`가 주기적으로 실행한다.

권장 초기 작업:

```text
daily_update
weekly_full_check
```

자동화 스크립트는 하나의 진입점으로 모은다.

예:

```bash
python -m quantpublisher.automation.daily_update
```

## 12. 실패 처리

각 단계는 실패 여부를 명확히 반환한다.

```text
crawler 실패
→ DB 업데이트 중단
→ report 생성 중단
→ 오류 로그 기록
→ 알림/수동 확인
```

불완전한 데이터를 이용해 정상 리포트를 생성하지 않는다.

## 13. 확장 시 지켜야 할 원칙

새 기술을 추가하기 전에 다음 질문을 한다.

1. SQLite로 해결할 수 없는가?
2. Python 표준 기능으로 해결할 수 없는가?
3. 기존 패키지로 해결할 수 없는가?
4. 운영 복잡성이 실제 이익보다 커지지 않는가?

네 질문 중 하나라도 충분히 해결 가능하다면 새 인프라를 추가하지 않는다.
