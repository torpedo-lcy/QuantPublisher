# 운영 가이드 (Task 012)

MVP 파이프라인을 처음부터 끝까지 재현하고, 정기적으로 점검하는 방법을 정리한다.
자동화 설치 자체는 `docs/AUTOMATION.md`를 참고한다.

```text
데이터 수집 → SQLite 저장 → Markdown 생성 → Hugo build → git commit/push → GitHub Pages
└──────── Python (daily_update) ────────┘  └─ Hugo ─┘  └ scripts/*.sh ┘  └─ Actions ─┘
```

각 단계가 실행되는 곳은 다음과 같다. 아래 절차의 소제목에 같은 표기를 쓴다.

| 표기 | 실행 위치 |
|---|---|
| **[Mac]** | Mac mini 터미널 |
| **[GitHub]** | GitHub 저장소 웹 화면 |
| **[Actions]** | GitHub Actions 러너 (사람이 직접 실행하지 않음) |

## 1. 처음부터 끝까지 재현 절차

### 1-1. [Mac] 설치와 테스트

```bash
cd /Users/home_lcy2/project/QuantPublisher
uv sync
uv run pytest
```

- 전체 테스트가 통과해야 한다.
- `tests/test_smoke_pipeline.py`가 수집 → 저장 → Markdown 생성 구간을 네트워크 없이 검증한다.

### 1-2. [Mac] 파이프라인 실행 (수집 → DB → Markdown)

```bash
uv run python -m quantpublisher.automation.daily_update
echo $?    # 0이면 성공
```

확인 항목:

```bash
# 저장된 종목 수
sqlite3 data/quantpublisher.sqlite3 "SELECT COUNT(*) FROM securities;"

# 생성된 content 수 (위 종목 수 중 활성 종목 수와 같아야 한다)
ls website/content/stocks | wc -l

# 마지막 실행 요약 로그
grep daily_update_summary logs/daily_update.log | tail -1
```

### 1-3. [Mac] Hugo 빌드 확인

```bash
cd website
hugo --gc --minify
ls public/stocks | head
```

- `hugo` 명령이 오류 없이 끝나야 한다.
- `website/public/stocks/<종목코드>/index.html`이 생성되었는지 확인한다.
- 로컬 빌드의 링크는 `hugo.yaml`의 `baseURL`(example.com) 기준이다. 실제 배포 URL은 Actions가 `--baseURL`로 덮어쓴다.

### 1-4. [Mac] commit / push

수동으로 하려면:

```bash
git status --short -- website/content | head
git add website/content
git commit -m "chore: daily report update $(date '+%Y-%m-%d')"
git push
```

파이프라인 실행부터 commit/push까지 한 번에 하려면 `./scripts/daily_update.sh`를 실행한다.

### 1-5. [Actions] 빌드와 배포

`main` 브랜치에 `website/**` 변경이 push되면 `.github/workflows/hugo.yml`이 자동 실행된다.
사람이 할 일은 없다.

### 1-6. [GitHub] 배포 결과 확인

- 저장소의 **Actions** 탭에서 최근 실행이 `build`, `deploy` 모두 성공인지 확인한다.
- 배포된 사이트에서 종목 페이지가 열리는지 확인한다.

## 2. 무엇이 자동으로 검증되고, 무엇이 수동인가

| 구간 | 검증 방법 | 위치 |
|---|---|---|
| 종목 목록 파싱·검증 | 자동 (pytest, fixture) | `tests/test_krx_listing.py` |
| DB 저장·중복 방지 | 자동 (pytest) | `tests/test_security_repository.py` |
| 지표 계산 | 자동 (pytest) | `tests/test_metrics.py` |
| 수집 → DB → Markdown 전체 흐름, 실패 시 중단 | 자동 (pytest) | `tests/test_daily_update.py`, `tests/test_smoke_pipeline.py` |
| 백테스트 재현성 | 자동 (pytest, fixture) | `tests/test_backtest.py` |
| 스크립트·plist·워크플로 파일 정합성 | 자동 (pytest) | `tests/test_smoke_pipeline.py` |
| 실제 KRX 수집 (네트워크) | **수동** | 1-2 |
| Hugo build | **수동** | 1-3 |
| git push (SSH 인증 포함) | **수동** | 1-4 |
| GitHub Actions 배포 | **수동** | 1-6 |
| launchd 스케줄 실행 | **수동** | `docs/AUTOMATION.md` 3절 |

## 3. 운영 체크리스트

### 3-1. 배포 전 (변경을 push하기 전)

- [ ] `uv run pytest` 전체 통과
- [ ] `uv run python -m quantpublisher.automation.daily_update` 종료 코드 0
- [ ] `cd website && hugo --gc --minify` 성공
- [ ] `git status`에 의도하지 않은 파일(`.env`, API Key, `*.sqlite3`, `logs/`)이 없음

### 3-2. 매일 (자동 실행 후 확인)

- [ ] `logs/launchd_daily_update.log`에 오늘 날짜의 `[daily_update] 완료` 줄이 있음
- [ ] `git push 실패` 문구가 없음 (아래 4-2 참고)
- [ ] GitHub Actions 최근 실행이 성공

### 3-3. 매주

- [ ] `logs/` 디렉터리 크기 확인 (로그 로테이션이 없다)
- [ ] `git log --oneline | head`로 commit이 push되고 있는지 확인
- [ ] `uv run pytest` 전체 통과 (환경 변화 감지)

## 4. 장애 대응

### 4-1. 파이프라인 실패 (종료 코드 1)

원인은 `logs/daily_update.log`의 `ERROR` 줄과 traceback에 있다.
crawler 단계가 실패하면 DB 업데이트와 리포트 생성은 실행되지 않고, 기존 content는 그대로 유지된다.
같은 명령을 다시 실행해도 데이터가 중복되지 않는다.

### 4-2. git push 실패

증상: `logs/launchd_daily_update.err.log`에 `Permission denied (publickey)`.
이 경우 commit은 로컬에 쌓이지만 GitHub에는 반영되지 않는다. 다음 push 성공 시 한꺼번에 올라간다.

- 원인 후보: launchd 실행 환경에서 SSH 키를 사용할 수 없음 (passphrase가 있는 키를 ssh-agent에 올려 둔 경우 등).
- 확인: **[Mac]** 터미널에서 `ssh -T git@github.com`, 그리고 `git remote -v`로 원격 URL 방식(SSH/HTTPS) 확인.
- 해결 후보 (택 1):
  - 원격 URL을 HTTPS로 바꾸고 macOS 키체인 credential helper 사용
  - passphrase 없는 저장소 전용 deploy key를 만들고 `~/.ssh/config`의 `IdentityFile`로 지정

### 4-3. Actions 실패

Actions 탭에서 실패한 단계 로그를 확인한다. 로컬 `hugo --gc --minify`가 성공하는데 Actions만 실패한다면 Hugo 버전 차이를 먼저 의심한다 (워크플로는 `HUGO_VERSION`을 고정한다).

### 4-4. 로그 읽는 법

`launchd_daily_update.err.log`는 Python 로거의 INFO 로그도 함께 받는다(로거가 stderr로 출력하기 때문). 이 파일에 내용이 있다고 해서 곧 오류는 아니다. 오류 여부는 `ERROR`, `실패` 문구와 종료 코드로 판단한다.

## 5. 알려진 제한과 후속 과제

MVP 범위에서는 고치지 않고 기록만 한다. 각 항목은 별도 Task로 다루는 것을 권장한다.

| # | 내용 | 영향 | 권장 조치 |
|---|---|---|---|
| 1 | 리포트의 생성 시각(front matter `date`, 본문 `생성 시각`)이 실행마다 바뀜 | 매 실행마다 모든 content 파일이 변경되어, `daily_update.sh`의 "변경 없으면 commit 생략"이 동작하지 않음. 2026-09-13, 09-14 실행 모두 2,740개 파일이 commit됨 | report 계층에서 내용이 같으면 파일을 다시 쓰지 않거나, 시각 대신 데이터 기준일을 사용 |
| 2 | launchd 실행에서 `git push` 실패 이력 (2026-09-14) | 자동 배포가 이어지지 않음 | 4-2 참고 |
| 3 | ~~시세·재무 데이터를 수집하지 않음~~ → Task 013~015에서 해결. 단, `market_data_import`는 아직 launchd에 등록되지 않음 | 가져오기를 수동 실행하지 않으면 지표가 마지막 가져오기 시점 값에 머무름. 배당수익률은 항상 `N/A` | 가져오기 주기(월 1회 등)를 정해 자동화 등록 |
| 4 | 백테스트가 파이프라인에 연결되어 있지 않음 (라이브러리 형태) | 웹사이트에 백테스트 결과가 노출되지 않음 | 가격 수집 이후 연결 |
| 5 | ~~`.gitignore`가 `.env`, `opendart_api.txt`만 포함~~ → `data/`, `*.db`, `*.sqlite3`, `.venv/`, `__pycache__/`, `logs/`, `website/public/` 등을 추가함 (DB 파일이 GitHub 100MB 제한에 걸려 push 실패하던 문제) | 이미 추적 중인 파일은 `git rm -r --cached`로 한 번 추적 해제해야 함 | **[Mac]** 아래 정리 절차 참고 |
| 6 | 로그 로테이션 없음 | `logs/daily_update.log`가 매일 약 2,740줄(약 0.5MB)씩 증가 | 주기적 정리 또는 로테이션 도입 |
| 7 | `hugo.yaml`의 `baseURL`이 `example.com` | 로컬 빌드 링크만 영향. 배포는 Actions가 덮어씀 | 필요할 때 실제 도메인으로 변경 |
