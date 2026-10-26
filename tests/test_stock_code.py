"""종목코드 형식 검증 (숫자/영문 대문자 6자리) 테스트."""

from __future__ import annotations

from quantpublisher.crawler.krx_listing import parse_krx_listing
from quantpublisher.crawler.price_import import PriceParseStats, parse_price_rows
from quantpublisher.database.stock_code import is_valid_stock_code


def test_is_valid_stock_code_accepts_digits_and_uppercase_letters_only() -> None:
    assert is_valid_stock_code("005930")
    assert is_valid_stock_code("0030R0")
    assert not is_valid_stock_code("0030r0")  # 소문자
    assert not is_valid_stock_code("12345")  # 5자리
    assert not is_valid_stock_code("1234567")  # 7자리
    assert not is_valid_stock_code("00 930")  # 공백
    assert not is_valid_stock_code("")
    assert not is_valid_stock_code("00593;")  # 쉘 메타문자


def test_parse_krx_listing_accepts_alphanumeric_code() -> None:
    result = parse_krx_listing([{"Code": "0030R0", "Name": "신규종목", "Market": "KOSPI"}])

    assert [s.stock_code for s in result] == ["0030R0"]


def test_parse_price_rows_accepts_alphanumeric_code_in_securities() -> None:
    stats = PriceParseStats()

    prices = list(parse_price_rows([("0030R0", 20261001, 1, 2, 1, 2, 10)], {"0030R0"}, stats))

    assert [p.stock_code for p in prices] == ["0030R0"]
    assert stats.skipped_invalid == 0
