# 자동화 (Task 010)

Mac mini에서 daily_update 파이프라인을 수동/자동으로 실행하는 방법을 설명한다.

## 1. 구성 요소

| 파일 | 역할 |
|---|---|
| `src/quantpublisher/automation/daily_update.py` | crawler → database → report 파이프라인 진입점 (Python) |
| `scripts/daily_update.sh` | Python 파이프라인 실행 + website content git commit/push (zsh) |
| `scripts/com.quantpublisher.dailyupdate.plist` | launchd 설정 예시 |

파이프라인 단계:

```text
1. init_db              DB 스키마 초기화 (idempotent)
2. collect_krx_listing   KRX 종목 목록 수집 → securities 테이블 upsert
3. 리포트 생성            활성 종목별 Markdown → website/content/stocks/*.md
```

3단계에서 종목마다 `financial_statements`(최신 연간)와 `financial_metrics`(최신 월)를
읽어 ROE·ROA·마진·부채비율·매출성장률·PER·PBR·EPS·BPS를 계산하고, 지표 옆에 기준
연도/월과 연결/별도 구분을 표시한다 (Task 015). 이 데이터는 `daily_update`가 수집하지
않으며, 별도로 실행한 `market_data_import`(docs/MARKET_DATA_IMPORT.md)가 저장해 둔 값을
읽기만 한다. 데이터가 없는 종목이나 지표는 `N/A`로 표시되고 파이프라인은 정상 종료한다.
배당수익률은 데이터가 없어 항상 `N/A`다. 매출성장률은 전년도 연간 데이터가 없거나
두 연도의 연결/별도 기준이 다르면 `N/A`다 (추정하지 않음).

이전 단계가 실패하면 다음 단계는 실행되지 않는다 (ARCHITECTURE.md 12절).

## 2. 수동 실행

### 2-1. Python 파이프라인만 실행

```bash
cd /Users/home_lcy2/project/QuantPublisher
uv run python -m quantpublisher.automation.daily_update
```

- 종료 코드 0: 성공
- 종료 코드 1: 실패 (원인은 `logs/daily_update.log`와 콘솔 출력을 확인)

### 2-2. git commit/push까지 포함한 전체 실행

```bash
cd /Users/home_lcy2/project/QuantPublisher
./scripts/daily_update.sh
```

`website/content`에 변경 사항이 있을 때만 commit/push한다. 변경 사항이
없으면 commit 없이 정상 종료(exit 0)한다.

## 3. launchd 자동 실행 설치

1. `scripts/com.quantpublisher.dailyupdate.plist`를 연다.
   - `ProgramArguments`의 `scripts/daily_update.sh` 경로를 실제 설치
     경로로 수정한다 (예시는 `/Users/home_lcy2/project/QuantPublisher`).
   - `StandardOutPath` / `StandardErrorPath` 경로도 동일하게 수정한다.
   - 필요하면 `StartCalendarInterval`의 `Hour`/`Minute`을 원하는 실행
     시각으로 수정한다 (기본값: 매일 07:30).

2. `scripts/daily_update.sh`에 실행 권한이 있는지 확인한다.

   ```bash
   chmod +x scripts/daily_update.sh
   ```

3. plist를 `~/Library/LaunchAgents/`에 복사한다.

   ```bash
   cp scripts/com.quantpublisher.dailyupdate.plist \
      ~/Library/LaunchAgents/com.quantpublisher.dailyupdate.plist
   ```

4. launchd에 등록하고 실행한다.

   ```bash
   launchctl load ~/Library/LaunchAgents/com.quantpublisher.dailyupdate.plist

   # 등록 직후 스케줄을 기다리지 않고 즉시 1회 실행해 동작을 확인하려면:
   launchctl start com.quantpublisher.dailyupdate
   ```

5. 로그를 확인한다.

   ```bash
   tail -f logs/launchd_daily_update.log
   tail -f logs/launchd_daily_update.err.log
   tail -f logs/daily_update.log   # Python 로거가 기록하는 상세 로그
   ```

## 4. 제거/재설치

```bash
launchctl unload ~/Library/LaunchAgents/com.quantpublisher.dailyupdate.plist
rm ~/Library/LaunchAgents/com.quantpublisher.dailyupdate.plist
```

plist 내용을 수정한 뒤에는 `unload` 후 다시 `load`해야 변경 사항이
반영된다.

## 5. 문제 해결

- **`uv 명령을 찾을 수 없습니다`**: launchd는 로그인 셸의 PATH를 상속하지
  않는다. `scripts/daily_update.sh`가 `/opt/homebrew/bin`,
  `~/.local/bin` 등 일반적인 설치 경로를 PATH에 직접 추가하므로, uv를
  다른 경로에 설치했다면 스크립트의 PATH 목록에 해당 경로를 추가한다.
- **`git push` 실패**: SSH 키/자격 증명이 launchd 실행 컨텍스트(비대화형
  셸)에서도 동작하는지 확인한다. `ssh-agent`에 키를 등록해 둔 경우
  launchd 세션에서는 접근하지 못할 수 있다.
- **파이프라인은 성공했는데 사이트에 반영되지 않음**: `website/content`
  변경 사항이 git에 commit/push되었는지, GitHub Actions(Task 009,
  `.github/workflows/hugo.yml`)가 정상적으로 실행되었는지 GitHub 저장소의
  Actions 탭에서 확인한다.
