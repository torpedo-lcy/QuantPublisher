# 외부 Mac 데이터 가져오기 (Task 013)

다른 Mac mini에 있는 `quant.db`(가격/종목/재무 통합 DB)를 읽어 이 프로젝트의 SQLite로 가져온다.

```text
[외부 Mac]  quant.db (.backup 스냅샷) ──ssh 스냅샷 → rsync──▶ [QuantPublisher Mac]
              v_adj_price (수정주가)     → prices_daily
              stock.corp_code           → securities.corp_code
              financial_q (결산월 분기)  → financial_statements
              quant_latest              → financial_metrics (최신 월)
```

원천 변경 (2026-10-26): 종목별 `stock-price/<종목코드>.db` + 이전 `quant.db`에서
`/Users/home/var/stockbot/DB/data/quant.db` 하나로 바뀌었다 (`meta.schema_version=1`).

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
QP_EXTERNAL_QUANT_DB_PATH=/Users/home/var/stockbot/DB/data/quant.db
```

- `QP_EXTERNAL_HOST`는 `~/.ssh/config`의 별칭도 된다. 이 경우 `QP_EXTERNAL_USER`는 비워 둔다.
- HOST를 넣었는데 `QP_EXTERNAL_QUANT_DB_PATH`가 없으면 시작할 때 바로 오류가 난다.
- 이전에 쓰던 `QP_EXTERNAL_STOCK_PRICE_DIR`는 더 이상 읽지 않는다 (남아 있어도 무시된다).

### 1-4. [외부 Mac] 데이터 형식 확인 (처음 한 번)
원본은 WAL 모드라, 쓰는 프로세스가 없을 때는 `-readonly`로 열리지 않는다 (`unable to open database file`).
확인할 때는 `immutable=1`로 연다.

```bash
sqlite3 "file:/Users/home/var/stockbot/DB/data/quant.db?immutable=1" "SELECT code, date, close FROM daily_price WHERE code='005930' ORDER BY date DESC LIMIT 3"
sqlite3 "file:/Users/home/var/stockbot/DB/data/quant.db?immutable=1" "SELECT code, corp_code, setl_month FROM stock LIMIT 3"
```

- `daily_price.date`는 정수 `YYYYMMDD`이고 `prices_daily.trade_date`에는 `YYYY-MM-DD`로 저장한다.
- `daily_price`는 원주가다. `prices_daily`는 이전 원천과 같은 **수정주가**로 저장하므로 `v_adj_price`의
  `adj_open/adj_high/adj_low/adj_close`를 쓰고, 거래량은 `volume / adj_factor`로 맞춘다 (소수 4자리 반올림).
  `v_adj_price`는 `corp_event`의 `REV_SPLIT`, `BONUS`, `CAP_DECREASE`만 보정한다 (배당은 보정하지 않음).
  무상감자가 있는 종목은 이전 원천과 보정 방식이 달라 과거 값이 10% 안팎 다를 수 있다.
- `corp_code`는 8자리 숫자여야 한다. 정수로 저장돼 앞의 0이 빠져 있으면 8자리로 0을 채워 저장한다.

## 2. 실행

**[QP Mac]**

```bash
cd /Users/home_lcy2/project/QuantPublisher
uv run python -m quantpublisher.automation.daily_update   # securities가 비어 있으면 먼저 한 번
uv run python -m quantpublisher.crawler.market_data_import
echo $?
```

원천을 바꾼 뒤 처음 한 번은 가격을 전체 기간으로 다시 가져와 덮어쓴다 (이전 원천과 종가가 다른 날이 있다).

```bash
uv run python -m quantpublisher.crawler.market_data_import --full-prices
```

| 종료 코드 | 의미 |
|---:|---|
| 0 | 성공 |
| 1 | 중단 (외부 Mac 접속/명령/전송 실패, 설정 없음, securities 비어 있음, 스냅샷 테이블 없음). 외부 접근 실패면 `prices_daily`는 바뀌지 않는다 |

로그: `logs/market_data_import.log` (요약 줄 `market_data_import_summary ...`).

## 3. 동작 규칙

- **스냅샷**: 매 실행마다 `quant.db` 전체(약 800MB)를 `.backup`으로 복사해 rsync로 가져온다.
  가격/corp_code/재무는 모두 이 파일 하나에서 읽는다.
- **최초 실행 / `--full-prices`**: 종목별 수정주가 전체를 가져온다 (백필, 같은 날짜는 원천 값으로 덮어씀).
- **재실행**: 종목별로 저장된 `MAX(trade_date)` 이후 행만 가져온다. 같은 날짜는 upsert라 중복되지 않는다.
- **재보정 감지**: 분할/병합/감자 이벤트가 새로 생기면 그 이전 날짜의 수정주가가 모두 바뀐다. 매 실행마다
  원천의 종목별 첫 거래일 수정종가를 저장된 값과 비교해, 다르면 그 종목만 전체를 다시 가져온다
  (`price_readjusted_full_refresh` 로그, 결과의 `stocks_readjusted`). 이벤트 날짜와 기록 시점이 달라도 잡힌다.
- 이전 원천에만 있던 날짜의 행(새 원천에 없는 기간)은 지우지 않고 남겨 둔다.
- **검증에서 건너뛰는 행** (모두 로그와 결과 건수에 남는다): `securities`에 없는 종목코드, 형식이 틀린 날짜,
  숫자가 아니거나 비어 있거나 음수인 가격/거래량. 가격 0은 허용한다 (거래정지일).
- `securities`에 없는 종목은 읽지 않는다 (`price_source_codes_not_in_securities`).
- 원격 DB는 읽기 전용으로만 연다. `-wal` 파일이 있으면(쓰는 프로세스가 있음) `mode=ro`, 없으면
  `immutable=1`로 연다. 원격에 만드는 것은 이번 실행 전용 임시 디렉터리(`/tmp/qp_quant.*`)뿐이고,
  그 안의 스냅샷을 rollback journal 모드로 바꾼 뒤 가져오고 바로 지운다.
- 로컬 중간 파일은 `data/raw/external/` (매 실행 때 비움, Git 제외).

## 4. 재무/밸류에이션 가져오기 (Task 014)

같은 실행(`market_data_import`)이 `quant.db` 스냅샷을 한 번 복사한 뒤, 이미 받은 파일로 아래를 이어서 가져온다.
추가 접속이나 설정은 없다.

```text
quant.db.financial_q (period 월 = stock.setl_month인 분기만) → financial_statements (report_type='11011')
quant.db.quant_latest (+ daily_price 종가, share_count 주식수) → financial_metrics (asof_date의 월)
```

| 규칙 | 내용 |
|---|---|
| 연간 판정 | `financial_q`는 분기 누적(YTD)이다. period의 월이 결산월(`setl_month`, 없으면 12)인 행을 연간으로 보고 `year = period / 100`. `*_ytd`가 연간 값 |
| 연결/별도 | 원천에 구분이 없어 모두 연결(`is_consolidated=1`)로 저장. 사용자 결정 (2026-10-26) |
| 밸류에이션 | `quant_latest`는 종목별 최신 1행이다. 실행할 때마다 그 달 행을 upsert하고 지난 달 행은 남긴다. 사용자 결정 (2026-10-26). PER/PSR/PCR은 최근 4분기(TTM) 기준이라 이전 원천(직전 연간 기준)과 값이 다르다 |
| 가져오지 않는 열 | `financial_q`의 `eps`, `bps`, `cfo_ytd`, `quant_latest`의 기타 팩터(`gpa`, `roe` 등) |
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
