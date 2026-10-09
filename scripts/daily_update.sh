#!/bin/zsh
#
# Quant Publisher - daily_update 실행 스크립트 (launchd에서 호출).
#
# 역할 분리 (ARCHITECTURE.md 10절):
#   1. 데이터 수집 -> DB 저장 -> 리포트(Markdown content) 생성
#        -> quantpublisher.automation.daily_update (Python)이 담당한다.
#   2. website content 변경 사항 git commit/push
#        -> 이 스크립트가 담당한다. push 후 GitHub Actions가 Hugo build와
#           Pages 배포를 수행한다 (.github/workflows/hugo.yml, Task 009).
#
# launchd는 로그인 셸의 PATH/환경 변수를 상속하지 않으므로, 이 스크립트
# 안에서 필요한 PATH를 직접 구성한다.
#
# 수동 실행:
#   ./scripts/daily_update.sh
#
# launchd 설치 방법: docs/AUTOMATION.md 참고.

SCRIPT_DIR="$(cd "$(dirname "${0:A}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Homebrew(Apple Silicon)와 uv의 일반적인 설치 경로를 PATH 앞에 추가한다.
export PATH="/opt/homebrew/bin:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

cd "${PROJECT_DIR}" || {
    echo "[daily_update] 프로젝트 디렉터리로 이동할 수 없습니다: ${PROJECT_DIR}" >&2
    exit 1
}

echo "[daily_update] 시작: $(date '+%Y-%m-%d %H:%M:%S')"

if ! command -v uv >/dev/null 2>&1; then
    echo "[daily_update] uv 명령을 찾을 수 없습니다. PATH를 확인하세요: ${PATH}" >&2
    exit 1
fi

# ── 1) 데이터 수집 + 리포트 생성 (Python) ──────────────────────────────
echo "[daily_update] 파이프라인 실행 (crawler -> database -> report)"
if ! uv run python -m quantpublisher.automation.daily_update; then
    echo "[daily_update] 파이프라인 실패. git 작업을 건너뜁니다." >&2
    exit 1
fi

# ── 2) website content 변경 사항 commit/push ───────────────────────────
if ! command -v git >/dev/null 2>&1; then
    echo "[daily_update] git 명령을 찾을 수 없습니다. commit/push를 건너뜁니다." >&2
    exit 0
fi

if [ -z "$(git status --porcelain -- website/content)" ]; then
    echo "[daily_update] website/content에 변경 사항이 없어 commit을 건너뜁니다."
    echo "[daily_update] 완료: $(date '+%Y-%m-%d %H:%M:%S')"
    exit 0
fi

if ! git add website/content; then
    echo "[daily_update] git add 실패." >&2
    exit 1
fi

if ! git commit -m "chore: daily report update $(date '+%Y-%m-%d')"; then
    echo "[daily_update] git commit 실패." >&2
    exit 1
fi

if ! git push; then
    echo "[daily_update] git push 실패. 원격 저장소 접근 권한/네트워크를 확인하세요." >&2
    exit 1
fi

echo "[daily_update] 완료: $(date '+%Y-%m-%d %H:%M:%S')"
