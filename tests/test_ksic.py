from __future__ import annotations

from quantpublisher.analysis.ksic import industry_division_code, industry_name


def test_industry_name_uses_two_digit_division() -> None:
    assert industry_name("264") == "전자부품, 컴퓨터, 영상, 음향 및 통신장비 제조업"
    assert industry_name("26429") == industry_name("264")
    assert industry_name("64992") == "금융업"


def test_industry_name_is_none_for_unknown_or_malformed_codes() -> None:
    assert industry_name("99") is None  # 표에 없는 중분류
    assert industry_name("A1") is None
    assert industry_name("2") is None
    assert industry_name("") is None
    assert industry_name(None) is None


def test_industry_division_code() -> None:
    assert industry_division_code(" 2612 ") == "26"
    assert industry_division_code("x") is None
