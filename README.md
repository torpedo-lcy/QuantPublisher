# Quant Publisher

Mac mini 한 대에서 실행되는 개인용 퀀트 데이터 수집·분석·리포트·정적 웹 퍼블리싱 시스템.

전체 설계는 `docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_RULE.md`를 참고한다.

## 현재 상태

Task 001 (프로젝트 초기화) 완료. 아직 데이터 수집, DB, 분석, 리포트, 웹사이트 기능은 구현되지 않았다.

## 요구 사항

- macOS
- Python 3.12 이상
- [uv](https://docs.astral.sh/uv/) (가상환경/의존성 관리)

## 설치

```bash
git clone <repo-url> QuantPublisher
cd QuantPublisher
uv sync
```

`uv sync`는 `pyproject.toml`에 정의된 의존성을 설치하고 `.venv`를 생성한다.

## 설정

```bash
cp .env.example .env
```

필요한 값을 `.env`에 채운다. `.env`는 Git에 커밋하지 않는다 (`.gitignore` 참고).

설정은 `config/settings.py`의 `get_settings()`를 통해 읽는다.

```python
from config.settings import get_settings

settings = get_settings()
print(settings.db_path)
```

## 테스트 실행

```bash
uv run pytest
```

또는 가상환경을 활성화한 뒤:

```bash
python -m pytest
```

## 디렉터리 구조

```text
QuantPublisher/
├── pyproject.toml       # 프로젝트 메타데이터 및 의존성
├── README.md
├── .gitignore
├── .env.example
├── config/
│   ├── __init__.py
│   └── settings.py      # 환경변수 기반 설정
├── src/
│   └── quantpublisher/
│       └── __init__.py  # 패키지 진입점 (crawler/database/analysis/report/automation은 이후 Task에서 추가)
└── tests/
    ├── test_bootstrap.py
    └── test_settings.py
```

이후 Task에서 `crawler/`, `database/`, `analysis/`, `report/`, `automation/` 등 하위 모듈이 `src/quantpublisher/` 아래 추가된다. 자세한 순서는 `docs/README.md`의 Task 목록을 참고한다.

## 개발 규칙

코드 스타일, 예외 처리, 로깅, DB, 테스트 명명 규칙 등은 `docs/DEVELOPMENT_RULE.md`를 따른다.
