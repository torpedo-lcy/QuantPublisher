# 외부 Mac 데이터 가져오기 (Task 013)

다른 Mac mini에 있는 가격 DB와 `quant.db`를 읽어 이 프로젝트의 SQLite로 가져온다.

```text
[외부 Mac]  stock-price/<종목코드>.db (daily)  ──ssh 추출 → rsync──▶ [QuantPublisher Mac] prices_daily
[외부 Mac]  quant.db (.backup 스냅샷)           ──ssh 스냅샷 → rsync──▶ [QuantPublisher Mac] securities.corp_code
```

실행 위치 표기: **[QP Mac]** = QuantPublisher가 있는 Mac mini, **[외부 Mac]** = 가격/재무 DB가 있는 Mac mini.

## 1. 사전 준비

### 1-1. [외부 Mac] 원격 로그인 켜기
시스템 설정 → 일반 → 공유 → 원격 로그인. 이 외에 외부 Mac에 설치하거나 바꾸는 것은 없다.

### 1-2. [QP Mac] 비밀번호 없이 SSH 접속되게 하기
자동 실행(launchd)에서도 쓰므로 키 인증이 필요하다. 이 프로젝트는 `BatchMode=yes`로 접속하므로
비밀번호 입력이 필요하면 멈추지 않고 즉시 실패한다.

```bash
ssh-copy-id <사용자>@<외부-Mac-호스트>     # 키가 없으면 먼저 ssh-keygen
ssh <사용자>@<외부-Mac-호스트> 'echo ok'   # 비밀번호 없이 ok가 나와야 한다
```

### 1-3. [QP Mac] `.env`에 접속 정보 넣기
`.env`는 Git에 커밋하지 않는다 (`.gitignore`에 포함).

```text
QP_EXTERNAL_HOST=mini2.local
QP_EXTERNAL_USER=quant
QP_EXTERNAL_STOCK_PRICE_DIR=/Users/quant/stock-price
QP_EXTERNAL_QUANT_DB_PATH=/Users/quant/quant.db
```

- `QP_EXTERNAL_HOST`는 `~/.ssh/config`의 별칭도 된다. 이 경우 `QP_EXTERNAL_USER`는 비워 둔다.
- HOST를 넣었는데 두 경로가 없으면 시작할 때 바로 오류가 난다.

### 1-4. [외부 Mac] 데이터 형식 확인 (처음 한 번)
검증이 `trade_date`를 `YYYY-MM-DD`로 엄격하게 확인하므로, 실제 형식을 먼저 본다.

```bash
sqlite3 -readonly /Users/quant/stock-price/005930.db "SELECT Time, close FROM daily ORDER BY Time DESC LIMIT 3"
sqlite3 -readonly /Users/quant/quant.db "SELECT stock_code, corp_code, typeof(corp_code) FROM stock_master LIMIT 3"
```

- `Time`이 `2026-09-30` 형태가 아니면(예: `2026-09-30 00:00:00`) 가져오기 결과의
  `rows_skipped_invalid`가 크게 나온다. 그 경우 알려 주면 변환 규칙을 정한다.
- `corp_code`는 8자리 숫자여야 한다. 정수로 저장돼 앞의 0이 빠져 있으면 8자리로 0을 채워 저장한다.

## 2. 실행

**[QP Mac]**

```bash
cd /Users/home_lcy2/project/QuantPublisher
uv run python -m quantpublisher.automation.daily_update   # securities가 비어 있으면 먼저 한 번
uv run python -m quantpublisher.crawler.market_data_import
echo $?
```

| 종료 코드 | 의미 |
|---:|---|
| 0 | 성공 |
| 1 | 중단 (외부 Mac 접속/명령/전송 실패, 설정 없음, securities 비어 있음). 이 경우 `prices_daily`는 바뀌지 않는다 |
| 2 | 일부 종목만 실패. 나머지는 저장됨. 실패 종목코드는 로그에 남는다 |

로그: `logs/market_data_import.log` (요약 줄 `market_data_import_summary ...`).

## 3. 동작 규칙

- **최초 실행**: 종목별 `daily` 전체를 가져온다 (백필). 종목 수와 기간에 따라 오래 걸릴 수 있다.
- **재실행**: 종목별로 저장된 `MAX(trade_date)` 이후 행만 가져온다. 같은 날짜는 upsert라 중복되지 않는다.
- **검증에서 건너뛰는 행** (모두 로그와 결과 건수에 남는다): `securities`에 없는 종목코드, 형식이 틀린 날짜,
  숫자가 아니거나 비어 있거나 음수인 가격/거래량. 가격 0은 허용한다 (거래정지일).
- `securities`에 없는 종목의 원격 파일은 요청 자체를 하지 않는다 (`price_remote_files_not_in_securities`).
- 원격 DB는 항상 `sqlite3 -readonly`로 연다. 원격에 만드는 것은 이번 실행 전용 임시 디렉터리
  (`/tmp/qp_export.*`, `/tmp/qp_quant.*`)뿐이고, 가져온 직후 지운다.
- 로컬 중간 파일은 `data/raw/external/` (매 실행 때 비움, Git 제외).

## 4. 재무/밸류에이션 가져오기 (Task 014)

같은 실행(`market_data_import`)이 `quant.db` 스냅샷을 한 번 복사한 뒤, 이미 받은 파일로 아래를 이어서 가져온다.
추가 접속이나 설정은 없다.

```text
quant.db.financial_data (report_type='11011' 연간만) → financial_statements
quant.db.market_data                                  → financial_metrics
```

| 규칙 | 내용 |
|---|---|
| 가져오지 않는 열 | `eps`(원천에서 항상 0), 현금흐름 3종, YoY 3종 |
| `net_income == 0.0` | "미공시"로 보고 `NULL`로 저장 (ROE 등이 0%로 계산되는 것을 막는다) |
| `sales == 0.0` | `NULL`로 저장 (마진/매출성장률이 0 기준으로 계산되는 것을 막는다) |
| `per == 0.0`, `pbr == 0.0` | "계산 불가"로 보고 `NULL`(=N/A)로 저장. 음수 PER/PBR(적자)은 그대로 |
| 그 외 열의 0 | `gross_profit`, `operating_income`, `psr`, `pcr` 등은 원천 값 그대로 |
| 건너뛰는 행 (로그와 결과 건수에 남음) | `securities`에 없는 종목, 숫자/영문 대문자 6자리가 아닌 종목코드, 연도가 2000~올해 밖, 존재하지 않는 `YYYY-MM`/날짜, 숫자가 아닌 값, 음수 종가·시총·주식수, 숫자가 전부 비어 있는 행 |
| 중복 | `(stock_code, year, report_type)`, `(stock_code, year_month)` 기준 upsert. 재실행해도 늘지 않고, 값이 바뀌면 갱신 |
| 원천 오류 | 파일/테이블/열이 없으면 `FinancialDataReadError`로 중단 (DB 쓰기 전에 확인하므로 `financial_*`는 바뀌지 않음, 종료 코드 1) |

로그 요약 줄: `financial_data_imported ...`, `financial_import_summary ...`
(`net_income_nullified`, `sales_nullified`, `per_pbr_nullified`는 `NULL`로 바꿔 저장한 행 수).

### 종목코드 형식
KRX가 신규 등록 종목(ETF/ETN, 스팩 등)에 부여하는 `0030R0` 같은 코드를 허용한다.
규칙은 숫자 또는 영문 대문자 6자리이고, `quantpublisher/database/stock_code.py` 한 곳에서 정의한다
(종목 목록, 가격, corp_code, 재무 가져오기, 외부 Mac 파일 목록이 모두 같은 규칙을 쓴다).
단, 재무/가격은 **`securities`에 등록된 종목만** 저장한다. 해당 코드가 `securities`에 없으면 여전히
건너뛰고 로그에 남는다.

## 5. 이 Task에서 하지 않은 것

`daily_update` 연결, 지표 계산(EPS/BPS 역산 포함), 리포트 반영은 Task 015에서 완료했다
(docs/AUTOMATION.md 1절). 이 가져오기는 아직 launchd에 등록되어 있지 않다.
