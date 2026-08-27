# Quant Publisher

Mac mini 한 대에서 실행되는 개인용 퀀트 데이터 수집·분석·리포트·정적 웹 퍼블리싱 시스템.

## 설치

```bash
uv sync
```

## 테스트 실행

```bash
uv run pytest
```

## 프로젝트 구조

- `src/quantpublisher/database/` - SQLite connection 및 Repository
- `src/quantpublisher/crawler/` - 외부 데이터 수집
- `src/quantpublisher/analysis/` - 투자 지표 계산
- `src/quantpublisher/report/` - Markdown 리포트 생성
- `src/quantpublisher/automation/` - 자동화 진입점
- `config/` - 설정 (settings.py)
- `data/` - SQLite DB 파일 및 원천 데이터
- `website/` - Hugo 정적 사이트
- `docs/` - 프로젝트 문서 (PROJECT_SPEC.md, ARCHITECTURE.md, DEVELOPMENT_RULE.md, TASKS/)

## DB 초기화

```python
from pathlib import Path
from quantpublisher.database.connection import connect, initialize_schema

with connect(Path("data/quantpublisher.sqlite3")) as conn:
    initialize_schema(conn)
```
