from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from quantpublisher.automation.company_info import HISTORY_DISPLAY_ITEMS, build_company_info
from quantpublisher.crawler.company_profile_import import (
    build_profile,
    import_company_profiles,
    parse_company_fields,
)
from quantpublisher.crawler.dart_client import (
    AnnualReportRef,
    DartApiError,
    DartError,
    DartRateLimitError,
)
from quantpublisher.database.company_profile_repository import CompanyProfileRepository
from quantpublisher.database.connection import get_connection, initialize_schema
from quantpublisher.database.models import CompanyProfile, Security
from quantpublisher.database.security_repository import SecurityRepository
from quantpublisher.report import StockMetrics, build_stock_report
from quantpublisher.report.markdown import render_stock_report_markdown

REPORT_XML = (
    "<DOCUMENT><SECTION-2><TITLE>1. 사업의 개요</TITLE><P>반도체를 만듭니다.</P></SECTION-2>"
    "<SECTION-2><TITLE>2. 회사의 연혁</TITLE>"
    "<P>사. 그 밖에 경영활동과 관련된 중요한 사항의 발생내용</P>"
    "<TABLE><TR><TD>2024</TD><TD>신공장 준공</TD></TR></TABLE></SECTION-2></DOCUMENT>"
)
COMPANY = {
    "status": "000",
    "induty_code": "264",
    "est_dt": "19690113",
    "ceo_nm": " 홍길동 ",
    "adres": "서울시  강남구",
    "hm_url": "www.example.com",
    "acc_mt": "12",
}
REPORT_REF = AnnualReportRef("20260310002820", "사업보고서 (2025.12)", "20260310", 2025)


class FakeDart:
    """DartClient 대역. 종목(corp_code)별 응답과 오류를 지정한다."""

    def __init__(self) -> None:
        self.companies: dict[str, dict | None] = {}
        self.reports: dict[str, AnnualReportRef | None] = {}
        self.xml: str | Exception = REPORT_XML
        self.company_errors: dict[str, Exception] = {}
        self.calls: list[str] = []

    def get_company(self, corp_code: str):
        self.calls.append(f"company:{corp_code}")
        if corp_code in self.company_errors:
            raise self.company_errors[corp_code]
        return self.companies.get(corp_code, COMPANY)

    def find_latest_annual_report(self, corp_code: str):
        self.calls.append(f"list:{corp_code}")
        return self.reports.get(corp_code, REPORT_REF)

    def fetch_report_xml(self, rcept_no: str) -> str:
        self.calls.append(f"doc:{rcept_no}")
        if isinstance(self.xml, Exception):
            raise self.xml
        return self.xml


@pytest.fixture
def connection(tmp_path: Path) -> sqlite3.Connection:
    conn = get_connection(tmp_path / "test.sqlite3")
    initialize_schema(conn)
    repo = SecurityRepository(conn)
    repo.upsert(Security("005930", "Samsung", "KOSPI"))
    repo.upsert(Security("000660", "Hynix", "KOSPI"))
    repo.upsert(Security("111111", "NoCorp", "KOSDAQ"))
    repo.upsert(Security("222222", "BadCorp", "KOSDAQ"))
    # upsert는 corp_code를 저장하지 않는다 (corp_code_import가 update_corp_codes로 채운다).
    repo.update_corp_codes({"005930": "00126380", "000660": "00164779", "222222": "12"})
    yield conn
    conn.close()


# ---- 순수 변환 -------------------------------------------------------------


def test_parse_company_fields_cleans_values() -> None:
    fields = parse_company_fields(COMPANY)

    assert fields == {
        "induty_code": "264",
        "established_date": "1969-01-13",
        "ceo_name": "홍길동",
        "address": "서울시 강남구",
        "homepage": "www.example.com",
        "fiscal_month": 12,
    }


@pytest.mark.parametrize(
    "company",
    [
        {"induty_code": "", "est_dt": "", "acc_mt": ""},
        {"induty_code": "abc", "est_dt": "19691345", "acc_mt": "13"},
        {"est_dt": "1969", "acc_mt": "x"},
        {},
    ],
)
def test_parse_company_fields_nulls_invalid_values(company: dict) -> None:
    fields = parse_company_fields(company)

    assert fields["induty_code"] is None
    assert fields["established_date"] is None
    assert fields["fiscal_month"] is None


def test_build_profile_combines_company_and_report_text() -> None:
    profile = build_profile("005930", COMPANY, REPORT_REF, REPORT_XML)

    assert profile.business_summary == "반도체를 만듭니다."
    assert json.loads(profile.history_json) == [[2024, "신공장 준공"]]  # type: ignore[arg-type]
    assert profile.report_rcept_no == "20260310002820"
    assert profile.report_year == 2025


def test_build_profile_without_report_has_only_company_fields() -> None:
    profile = build_profile("005930", COMPANY)

    assert profile.induty_code == "264"
    assert profile.business_summary is None
    assert profile.history_json is None
    assert profile.report_rcept_no is None


# ---- 저장소 ----------------------------------------------------------------


def test_repository_upsert_overwrites_with_none(connection: sqlite3.Connection) -> None:
    repo = CompanyProfileRepository(connection)
    repo.upsert(CompanyProfile("005930", induty_code="264", business_summary="요약"))

    repo.upsert(CompanyProfile("005930", induty_code="265"))
    found = repo.get("005930")

    assert found is not None
    assert found.induty_code == "265"
    assert found.business_summary is None
    assert repo.list_stock_codes() == {"005930"}
    assert set(repo.list_all()) == {"005930"}
    assert repo.get("000660") is None


# ---- 일괄 수집 -------------------------------------------------------------


def test_import_saves_only_targets_with_valid_corp_code(connection: sqlite3.Connection) -> None:
    result = import_company_profiles(connection, FakeDart())  # type: ignore[arg-type]

    assert result.targets == 2
    assert result.requested == 2
    assert result.saved == 2
    assert result.with_summary == 2
    assert result.with_history == 2
    assert CompanyProfileRepository(connection).list_stock_codes() == {"005930", "000660"}


def test_import_skips_existing_unless_refresh(connection: sqlite3.Connection) -> None:
    import_company_profiles(connection, FakeDart(), stock_codes=["005930"])  # type: ignore[arg-type]
    client = FakeDart()

    again = import_company_profiles(connection, client)  # type: ignore[arg-type]

    assert again.skipped_existing == 1
    assert again.saved == 1
    assert "company:00126380" not in client.calls

    refreshed = import_company_profiles(connection, FakeDart(), refresh=True)  # type: ignore[arg-type]
    assert refreshed.saved == 2


def test_import_respects_limit_and_codes(connection: sqlite3.Connection) -> None:
    limited = import_company_profiles(connection, FakeDart(), limit=1)  # type: ignore[arg-type]
    assert limited.saved == 1

    only = import_company_profiles(connection, FakeDart(), stock_codes=["000660"], refresh=True)  # type: ignore[arg-type]
    assert only.requested == 1


def test_import_without_reports_makes_one_call_per_stock(connection: sqlite3.Connection) -> None:
    client = FakeDart()

    result = import_company_profiles(connection, client, fetch_reports=False)  # type: ignore[arg-type]

    assert result.saved == 2
    assert result.with_report == 0
    assert all(call.startswith("company:") for call in client.calls)


def test_import_stops_immediately_on_rate_limit(connection: sqlite3.Connection) -> None:
    client = FakeDart()
    # 대상은 종목코드 순이므로 000660(00164779)이 먼저 처리된다.
    client.company_errors["00164779"] = DartRateLimitError("limit")

    result = import_company_profiles(connection, client)  # type: ignore[arg-type]

    assert result.rate_limited
    assert result.saved == 0
    assert "company:00126380" not in client.calls  # 다음 종목을 호출하지 않는다


def test_import_does_not_save_when_report_download_fails(connection: sqlite3.Connection) -> None:
    client = FakeDart()
    client.xml = DartError("network")

    result = import_company_profiles(connection, client)  # type: ignore[arg-type]

    assert result.failed == 2
    assert sorted(result.failed_codes) == ["000660", "005930"]
    assert CompanyProfileRepository(connection).list_stock_codes() == set()  # 다음에 다시 시도


def test_import_saves_company_only_when_document_is_missing(connection: sqlite3.Connection) -> None:
    client = FakeDart()
    client.xml = DartApiError("014", "파일이 존재하지 않습니다.")

    result = import_company_profiles(connection, client, stock_codes=["005930"])  # type: ignore[arg-type]

    profile = CompanyProfileRepository(connection).get("005930")
    assert result.saved == 1 and result.failed == 0
    assert profile is not None
    assert profile.induty_code == "264"
    assert profile.business_summary is None


def test_import_propagates_other_dart_api_errors_as_failures(connection: sqlite3.Connection) -> None:
    client = FakeDart()
    client.xml = DartApiError("800", "점검중")

    result = import_company_profiles(connection, client, stock_codes=["005930"])  # type: ignore[arg-type]

    assert result.failed == 1 and result.saved == 0


def test_import_counts_companies_without_data(connection: sqlite3.Connection) -> None:
    client = FakeDart()
    client.companies["00126380"] = None

    result = import_company_profiles(connection, client, stock_codes=["005930"])  # type: ignore[arg-type]

    assert result.no_company_data == 1 and result.saved == 0


# ---- 리포트 -----------------------------------------------------------------


def test_build_company_info_maps_fields_and_tolerates_bad_history() -> None:
    profile = CompanyProfile(
        "005930",
        induty_code="264",
        history_json=json.dumps([[2024, "a"], [2023, "b"]]),
        homepage="www.example.com",
    )

    info = build_company_info(profile)

    assert info is not None
    assert info.industry_name == "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업"
    assert info.history == ((2024, "a"), (2023, "b"))
    assert build_company_info(None) is None
    assert build_company_info(CompanyProfile("005930", history_json="not json")).history == ()  # type: ignore[union-attr]


def test_build_company_info_limits_displayed_history() -> None:
    many = json.dumps([[2000 + i, f"사건{i}"] for i in range(HISTORY_DISPLAY_ITEMS + 10)])

    info = build_company_info(CompanyProfile("005930", history_json=many))

    assert info is not None
    assert len(info.history) == HISTORY_DISPLAY_ITEMS


def _render(profile: CompanyProfile | None) -> str:
    security = Security("005930", "Samsung", "KOSPI")
    report = build_stock_report(security, StockMetrics(), company=build_company_info(profile))
    return render_stock_report_markdown(report)


def test_markdown_renders_company_section() -> None:
    markdown = _render(
        CompanyProfile(
            "005930",
            induty_code="264",
            established_date="1969-01-13",
            ceo_name="홍길동",
            address="서울",
            homepage="www.example.com",
            fiscal_month=12,
            business_summary="반도체를 만듭니다.",
            history_json=json.dumps([[2024, "신공장 준공"]]),
            report_year=2025,
        )
    )

    assert "## 기업 개요" in markdown
    assert markdown.index("## 주요 지표") < markdown.index("## 기업 개요")
    assert "| 업종 | 전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업 (KSIC 264) |" in markdown
    assert "| 설립일 | 1969-01-13 |" in markdown
    assert "| 홈페이지 | `www.example.com` |" in markdown
    assert "| 결산월 | 12월 |" in markdown
    assert "### 사업 내용\n\n반도체를 만듭니다." in markdown
    assert "- **2024**\n  - 신공장 준공" in markdown
    assert "출처: DART 사업보고서 (2025년 사업연도)에서 발췌" in markdown


def test_markdown_groups_history_by_year_newest_first() -> None:
    markdown = _render(
        CompanyProfile(
            "005930",
            history_json=json.dumps([[2024, "가"], [2024, "나"], [2023, "다"]]),
        )
    )

    assert "- **2024**\n  - 가\n  - 나\n- **2023**\n  - 다" in markdown


def test_markdown_omits_company_section_without_profile_and_empty_rows() -> None:
    assert "기업 개요" not in _render(None)

    sparse = _render(CompanyProfile("005930", ceo_name="홍길동"))
    assert "| 대표자 | 홍길동 |" in sparse
    assert "| 설립일" not in sparse
    assert "### 사업 내용" not in sparse
    assert "### 연혁" not in sparse
    assert "출처:" not in sparse


def test_markdown_neutralizes_hugo_shortcodes_and_markdown_in_external_text() -> None:
    markdown = _render(
        CompanyProfile(
            "005930",
            ceo_name="김|철수",
            business_summary='{{< pricechart code="x" >}} <script>alert(1)</script> [링크](http://evil) *굵게*',
            history_json=json.dumps([[2024, "{{% raw %}} | 1. 항목 `코드`"]]),
            homepage="a`b`.com",
        )
    )

    assert "{{<" not in markdown.split("## 기업 개요")[1]
    assert "{{%" not in markdown
    assert "<script>" not in markdown
    assert "[링크]" not in markdown.replace("\\[링크\\]", "")
    assert "| 대표자 | 김\\|철수 |" in markdown
    assert "| 홈페이지 | `ab.com` |" in markdown
