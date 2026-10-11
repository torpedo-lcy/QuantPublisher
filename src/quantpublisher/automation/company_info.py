"""저장된 기업 개요(CompanyProfile)를 리포트용 CompanyInfo로 바꾼다 (Task 019).

DB에 접근하지 않는 순수 함수만 둔다. 업종명은 저장하지 않고 업종코드에서 그때그때
계산한다(KSIC 표가 바뀌어도 DB를 다시 채울 필요가 없다).
"""

from __future__ import annotations

import json
import logging

from quantpublisher.analysis.ksic import industry_name
from quantpublisher.database.models import CompanyProfile
from quantpublisher.report import CompanyInfo

logger = logging.getLogger(__name__)

# 페이지에 싣는 연혁 항목 수의 상한 (저장된 것 중 최신 항목부터).
HISTORY_DISPLAY_ITEMS = 15


def build_company_info(profile: CompanyProfile | None) -> CompanyInfo | None:
    """CompanyProfile로 CompanyInfo를 만든다. 프로필이 없으면 None."""
    if profile is None:
        return None
    return CompanyInfo(
        industry_code=profile.induty_code,
        industry_name=industry_name(profile.induty_code),
        established_date=profile.established_date,
        ceo_name=profile.ceo_name,
        address=profile.address,
        homepage=profile.homepage,
        fiscal_month=profile.fiscal_month,
        business_summary=profile.business_summary,
        history=_parse_history(profile.stock_code, profile.history_json),
        report_year=profile.report_year,
    )


def _parse_history(stock_code: str, history_json: str | None) -> tuple[tuple[int, str], ...]:
    """history_json을 (연도, 내용) 튜플로 읽는다. 깨진 JSON은 연혁 없음으로 처리한다."""
    if not history_json:
        return ()
    try:
        raw = json.loads(history_json)
        items = tuple((int(year), str(text)) for year, text in raw)
    except (ValueError, TypeError):
        logger.warning("company_history_invalid stock_code=%s", stock_code)
        return ()
    return items[:HISTORY_DISPLAY_ITEMS]
