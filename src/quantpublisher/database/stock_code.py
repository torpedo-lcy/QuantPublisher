"""종목코드 형식 검증 (프로젝트 공통).

KRX는 신규 등록 종목(ETF/ETN, 스팩 등)에 숫자 6자리가 아니라 영문 대문자가 섞인
6자리 코드(예: ``0030R0``)를 부여한다. 이런 종목도 저장할 수 있도록 숫자 또는 영문
대문자 6자리를 허용한다. 소문자, 공백, 5자리/7자리는 허용하지 않는다.
"""

from __future__ import annotations

import re

STOCK_CODE_PATTERN = re.compile(r"^[0-9A-Z]{6}$")


def is_valid_stock_code(code: str) -> bool:
    """숫자 또는 영문 대문자로 이루어진 6자리 종목코드이면 True."""
    return STOCK_CODE_PATTERN.match(code) is not None
