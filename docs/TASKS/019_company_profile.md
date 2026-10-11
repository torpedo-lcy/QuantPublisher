# Task 019 - 기업 개요 수집 (업종, 설립일, 사업 내용, 연혁)

## 목표

종목 페이지에 "기업 개요" 섹션(업종, 설립일, 대표자, 본점, 홈페이지, 결산월, 사업 내용, 연혁)을 추가한다.
원천은 OpenDART다. API 키는 `.env`의 `QP_DART_API_KEY`에 둔다.

## 계획과 달라진 점

- 계획은 업종·상장일을 FinanceDataReader `KRX-DESC`로 받는 것이었으나, 해당 목록이 업스트림에서
  HTTP 404를 돌려주고(FDR 0.9.202, 2026-10-11 확인) 일반 `KRX` 목록에는 업종 컬럼이 없다.
  그래서 업종은 DART `company.json`의 업종코드(KSIC)로 대체했다.
- **상장일은 수집하지 못했다.** 대신 설립일을 쓴다.
- 업종명은 DART가 주지 않아 KSIC 중분류(앞 두 자리) 이름 표를 `analysis/ksic.py`에 두었다.
  표에 없는 코드는 이름을 지어내지 않고 코드만 표시한다.

## 구현 내용

- DB: 새 테이블 `company_profiles` (`database/connection.py`), 모델 `CompanyProfile`,
  `database/company_profile_repository.py`. `securities`는 바꾸지 않았다.
- `crawler/dart_client.py`: company.json / list.json / document.xml 호출.
  요청 간격 0.15초, 한도 초과(status 020)는 `DartRateLimitError`, 키와 URL은 예외·로그에 넣지 않는다.
  `[첨부정정]` 공시는 본문이 없어 건너뛴다.
- `crawler/dart_report_parser.py` (순수 함수): 사업보고서 XML에서 "사업의 개요" 발췌(700자 이내, 문장 끝에서 자름,
  `☞ ... 참고` 안내문 제거)와 연혁(연도당 5개, 최대 40개)을 뽑는다.
- `crawler/company_profile_import.py`: 종목별 즉시 저장, 이미 저장된 종목은 건너뛰어 이어서 실행 가능.
  보고서 다운로드 오류 시에는 저장하지 않아 다음 실행에서 다시 시도한다. 원문이 없는 공시(status 014,
  일부 금융지주)는 기업개황만 저장한다.
- `automation/company_info.py` + 템플릿: 리포트에 "기업 개요" 섹션. DART 텍스트는 Markdown 특수문자를
  이스케이프하고 Hugo shortcode(`{{`)가 실행되지 않도록 깨뜨린다. 홈페이지는 링크가 아니라 코드로 표시한다.
- `config/settings.py`: `dart_api_key` (repr에 노출되지 않음).

## 실행 방법

```bash
uv run python -m quantpublisher.crawler.company_profile_import --codes 005930 000660   # 일부
uv run python -m quantpublisher.crawler.company_profile_import --limit 100             # 100개만 (이어서 실행 가능)
uv run python -m quantpublisher.crawler.company_profile_import                         # 전체 (corp_code가 있는 활성 종목)
uv run python -m quantpublisher.crawler.company_profile_import --no-report             # 기업개황만 (종목당 1건)
uv run python -m quantpublisher.crawler.company_profile_import --refresh               # 저장된 종목도 다시
```

종료 코드: 0 성공 / 1 중단(키 없음, 한도 초과) / 2 일부 종목 실패. 로그는 `logs/company_profile_import.log`.
사업보고서는 연 1회 갱신되므로 수집은 연 1~2회면 충분하다. `daily_update`는 저장된 값을 읽기만 한다.

## 표본 수집 결과 (2026-10-11, 39개 종목)

- 저장 39/39, 사업 요약 37개, 연혁 19개. 업종코드·설립일은 전부.
- 연혁이 없는 종목의 대부분은 원문에 연혁 항목이 없다("해당사항 없음"). 일부(약 4개 중 1개 수준)는
  형식이 달라 읽지 못했다.
- 호출 규모 추정: 전체 약 2,650개 종목 × 3건(약 8,000건). 일 한도 20,000건 안이다.

## 알려진 제한

- 연혁은 "그 밖에 경영활동과 관련된 중요한 사항의 발생내용" 또는 "당해 기업의 연혁" 소제목이 있을 때만 추출한다.
  그 밖의 형식은 임원·주주 변동표의 날짜가 연혁으로 섞일 위험이 있어 읽지 않는다 (누락이 오탐보다 낫다).
- 사업 요약은 원문의 첫 부분이라 회사에 따라 사업 설명보다 회사 구성 설명이 먼저 나올 수 있다.
- 업종 이름은 중분류(예: "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업")라 세분류 정보는 없다.
  코드(KSIC 3~5자리)는 저장해 두었다.
- 상장일은 없다.

## 남은 TODO

- 전체 종목 수집 실행 (사용자 확인 후).
- 시각 확인은 `hugo server`의 `/stocks/005930/`, `/stocks/105560/`(본문 없는 금융지주), `/stocks/311690/` 등으로.

## 다음 Task

Task 020 - 동종업종·시장 비교 (업종코드로 동종 그룹을 만든다).
