# Quant Publisher

Mac mini 한 대에서 실행되는 개인용 퀀트 데이터 수집·분석·리포트·정적 웹 퍼블리싱 시스템.

```text
KRX 종목 수집 → SQLite → 분석/백테스트 → Markdown → Hugo → GitHub Pages
```

## 설치

```bash
uv sync
```

## 테스트 실행

```bash
uv run pytest
```

## 빠른 실행

```bash
# 수집 → DB 저장 → Markdown(website/content/stocks) 생성
uv run python -m quantpublisher.automation.daily_update

# Hugo 빌드 확인
cd website && hugo --gc --minify
```

commit/push까지 포함한 실행과 launchd 자동 실행은 `docs/AUTOMATION.md`,
처음부터 끝까지의 재현 절차와 점검 체크리스트는 `docs/OPERATIONS.md`를 참고한다.

## 프로젝트 구조

- `src/quantpublisher/database/` - SQLite connection 및 Repository
- `src/quantpublisher/crawler/` - 외부 데이터 수집 (KRX 종목 목록)
- `src/quantpublisher/analysis/` - 투자 지표 계산
- `src/quantpublisher/backtest/` - 단일 전략 백테스트
- `src/quantpublisher/report/` - Markdown 리포트 생성
- `src/quantpublisher/automation/` - 자동화 진입점 (`daily_update`)
- `config/` - 설정 (settings.py)
- `data/` - SQLite DB 파일 및 원천 데이터
- `scripts/` - 실행 스크립트, launchd plist
- `website/` - Hugo 정적 사이트
- `.github/workflows/` - GitHub Pages 배포 (GitHub Actions)
- `docs/` - 프로젝트 문서

## 문서

| 문서 | 내용 |
|---|---|
| `docs/PROJECT_SPEC.md` | 프로젝트 사양 |
| `docs/ARCHITECTURE.md` | 계층 구조와 데이터 흐름 |
| `docs/DEVELOPMENT_RULE.md` | 개발 규칙 |
| `docs/AUTOMATION.md` | daily_update와 launchd 설치 |
| `docs/OPERATIONS.md` | 재현 절차, 운영 체크리스트, 장애 대응, 알려진 제한 |
| `docs/TASKS/` | Task 문서 (001~012) |

## DB 초기화

```python
from pathlib import Path
from quantpublisher.database.connection import connect, initialize_schema

with connect(Path("data/quantpublisher.sqlite3")) as conn:
    initialize_schema(conn)
```
