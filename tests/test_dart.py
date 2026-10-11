from __future__ import annotations

import io
import json
import zipfile

import pytest

from quantpublisher.crawler import dart_client
from quantpublisher.crawler.dart_client import (
    DartApiError,
    DartClient,
    DartError,
    DartRateLimitError,
    pick_latest_annual_report,
)
from quantpublisher.crawler.dart_report_parser import (
    HISTORY_MAX_PER_YEAR,
    extract_business_summary,
    extract_history,
)


def _section(title: str, body: str, level: int = 2) -> str:
    return f"<SECTION-{level}><TITLE>{title}</TITLE>{body}</SECTION-{level}>"


def _doc(*sections: str) -> str:
    return "<DOCUMENT><BODY>" + "".join(sections) + "</BODY></DOCUMENT>"


# ---- 공시 목록 선택 -------------------------------------------------------


def test_pick_latest_annual_report_prefers_latest_receipt_and_reads_fiscal_year() -> None:
    items = [
        {"rcept_no": "20250311001085", "report_nm": "사업보고서 (2024.12)", "rcept_dt": "20250311"},
        {"rcept_no": "20260310002820", "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260310"},
        {"rcept_no": "20260101000001", "report_nm": "감사보고서", "rcept_dt": "20260401"},
    ]

    ref = pick_latest_annual_report(items)

    assert ref is not None
    assert ref.rcept_no == "20260310002820"
    assert ref.fiscal_year == 2025


def test_pick_latest_annual_report_skips_attachment_only_corrections() -> None:
    items = [
        {"rcept_no": "1", "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260310"},
        {"rcept_no": "2", "report_nm": "[첨부정정]사업보고서 (2025.12)", "rcept_dt": "20260327"},
        {"rcept_no": "3", "report_nm": "[첨부추가]사업보고서 (2025.12)", "rcept_dt": "20260401"},
    ]

    assert pick_latest_annual_report(items).rcept_no == "1"  # type: ignore[union-attr]
    assert pick_latest_annual_report(items[1:]) is None


def test_pick_latest_annual_report_includes_corrections_and_handles_none() -> None:
    items = [
        {"rcept_no": "1", "report_nm": "사업보고서 (2024.12)", "rcept_dt": "20250311"},
        {"rcept_no": "2", "report_nm": "[기재정정]사업보고서 (2024.12)", "rcept_dt": "20250401"},
    ]

    assert pick_latest_annual_report(items).rcept_no == "2"  # type: ignore[union-attr]
    assert pick_latest_annual_report([]) is None
    assert pick_latest_annual_report([{"rcept_no": "3", "report_nm": "분기보고서"}]) is None


# ---- 클라이언트 오류 처리 (네트워크는 monkeypatch) --------------------------


def _client_returning(monkeypatch: pytest.MonkeyPatch, raw: bytes) -> DartClient:
    client = DartClient("test-key", min_interval=0)
    monkeypatch.setattr(client, "_request", lambda path, params: raw)
    return client


def test_client_rejects_blank_key() -> None:
    with pytest.raises(ValueError):
        DartClient("   ")


def test_get_company_returns_none_for_no_data_and_raises_for_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_data = _client_returning(monkeypatch, json.dumps({"status": "013"}).encode())
    assert no_data.get_company("00000001") is None

    limited = _client_returning(monkeypatch, json.dumps({"status": "020"}).encode())
    with pytest.raises(DartRateLimitError):
        limited.get_company("00000001")

    bad_key = _client_returning(monkeypatch, json.dumps({"status": "010", "message": "x"}).encode())
    with pytest.raises(DartApiError) as info:
        bad_key.get_company("00000001")
    assert info.value.status == "010"


def test_fetch_report_xml_reads_main_xml_from_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("123.xml", "<DOCUMENT>본문</DOCUMENT>")
        archive.writestr("123_00760.xml", "<other/>")
    client = _client_returning(monkeypatch, buffer.getvalue())

    assert client.fetch_report_xml("123") == "<DOCUMENT>본문</DOCUMENT>"


def test_fetch_report_xml_reports_error_body_status(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"<result><status>014</status><message>file missing</message></result>"
    with pytest.raises(DartApiError) as info:
        _client_returning(monkeypatch, body).fetch_report_xml("123")
    assert info.value.status == "014"

    limited = b"<result><status>020</status><message>limit</message></result>"
    with pytest.raises(DartRateLimitError):
        _client_returning(monkeypatch, limited).fetch_report_xml("123")

    with pytest.raises(DartError):
        _client_returning(monkeypatch, b"garbage").fetch_report_xml("123")


def test_fetch_report_xml_rejects_zip_without_main_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other.xml", "<x/>")

    with pytest.raises(DartError):
        _client_returning(monkeypatch, buffer.getvalue()).fetch_report_xml("123")


def test_client_errors_never_contain_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def boom(*args, **kwargs):
        raise urllib.error.URLError("failed https://opendart.fss.or.kr/api/x?crtfc_key=SECRETKEY")

    monkeypatch.setattr(dart_client.urllib.request, "urlopen", boom)
    client = DartClient("SECRETKEY", min_interval=0)

    with pytest.raises(DartError) as info:
        client.get_company("00000001")

    assert "SECRETKEY" not in str(info.value)
    # 원인 예외(URL 포함)를 체인에 남기지 않는다.
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


# ---- 사업의 개요 -----------------------------------------------------------


def test_extract_business_summary_strips_tags_and_reference_lines() -> None:
    xml = _doc(
        _section(
            "1. 사업의 개요",
            "<P>당사는 반도체를 만드는 회사입니다.</P><P>☞ 자세한 사항은 참고하시기 바랍니다.</P>"
            "<P>주요 제품은 &amp; 메모리입니다.</P>",
        ),
        _section("2. 주요 제품 및 서비스", "<P>다른 섹션</P>"),
    )

    assert extract_business_summary(xml) == "당사는 반도체를 만드는 회사입니다. 주요 제품은 & 메모리입니다."


def test_extract_business_summary_removes_inline_reference_notes() -> None:
    xml = _doc(
        _section(
            "1. 사업의 개요",
            "<P>당사는 TV를 만듭니다.☞ 자세한 사항은 '7. 기타 참고사항'을 참고하시기 바랍니다. "
            "해외에도 판매합니다.</P><P>☞ 줄 전체가 안내문입니다</P>",
        )
    )

    assert extract_business_summary(xml) == "당사는 TV를 만듭니다. 해외에도 판매합니다."


def test_extract_business_summary_cuts_long_text_at_sentence_end() -> None:
    sentence = "당사는 제품을 생산하여 판매합니다."
    xml = _doc(_section("1. 사업의 개요", "<P>" + sentence * 100 + "</P>"))

    summary = extract_business_summary(xml, max_chars=100)

    assert summary is not None
    assert len(summary) <= 100
    assert summary.endswith("다.")


def test_extract_business_summary_is_none_when_missing_or_empty() -> None:
    assert extract_business_summary(_doc(_section("2. 주요 제품", "<P>x</P>"))) is None
    assert extract_business_summary(_doc(_section("1. 사업의 개요", "<P></P>"))) is None


# ---- 연혁 ------------------------------------------------------------------


def test_extract_history_reads_year_table_and_stops_at_numbered_subsection() -> None:
    body = (
        "<P>가. 회사의 본점소재지 및 그 변경</P><P>수원입니다.</P>"
        "<P>사. 그 밖에 경영활동과 관련된 중요한 사항의 발생내용</P>"
        "<TABLE><TR><TD>2023</TD><TD>AI 반도체 개발</TD></TR>"
        "<TR><TD>2024</TD><TD>신공장 준공</TD></TR>"
        "<TR><TD></TD><TD>해외 법인 설립</TD></TR></TABLE>"
        "<P>(2) 조직의 변경</P><P>조직 설명 문장입니다.</P>"
    )
    xml = _doc(_section("2. 회사의 연혁", body))

    history = extract_history(xml)

    assert [(h.year, h.text) for h in history] == [
        (2024, "신공장 준공"),
        (2024, "해외 법인 설립"),
        (2023, "AI 반도체 개발"),
    ]


def test_extract_history_reads_old_format_with_year_month_prefix() -> None:
    body = (
        "<P>가. 당해 기업의 연혁</P>"
        "<TABLE><TR><TD>일 자</TD><TD>내 용</TD></TR>"
        "<TR><TD>2020. 01</TD><TD>업무협약 체결</TD></TR>"
        "<TR><TD>2021. 03</TD><TD>호주 법인 설립</TD></TR></TABLE>"
        "<P>나. 회사의 본점 소재지 및 그 변경</P><P>2019.01 서울 이전</P>"
    )
    xml = _doc(_section("2. 회사의 연혁", body))

    history = extract_history(xml)

    assert [(h.year, h.text) for h in history] == [(2021, "호주 법인 설립"), (2020, "업무협약 체결")]


def test_extract_history_reads_inline_year_prefixed_lines() -> None:
    body = (
        "<P>사. 그 밖에 경영활동과 관련된 중요한 사항의 발생내용</P>"
        "<P>2022년 5월 코스닥 상장</P><P>- 2021.11 제2공장 준공</P>"
    )
    xml = _doc(_section("2. 회사의 연혁", body))

    assert [(h.year, h.text) for h in extract_history(xml)] == [
        (2022, "코스닥 상장"),
        (2021, "제2공장 준공"),
    ]


def test_extract_history_is_empty_when_no_events() -> None:
    no_heading = _doc(_section("2. 회사의 연혁", "<P>가. 본점</P><P>서울</P>"))
    none_happened = _doc(
        _section(
            "2. 회사의 연혁",
            "<P>사. 그 밖에 경영활동과 관련된 중요한 사항의 발생내용최근 5사업연도 중 해당사항 없습니다.</P>",
        )
    )

    assert extract_history(no_heading) == []
    assert extract_history(none_happened) == []
    assert extract_history(_doc()) == []


def test_extract_history_limits_events_per_year() -> None:
    rows = "".join(f"<TR><TD>2024</TD><TD>사건 번호 {i}번 진행</TD></TR>" for i in range(10))
    body = "<P>사. 그 밖에 경영활동과 관련된 중요한 사항의 발생내용</P><TABLE>" + rows + "</TABLE>"

    history = extract_history(_doc(_section("2. 회사의 연혁", body)))

    assert len(history) == HISTORY_MAX_PER_YEAR
