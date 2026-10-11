"""DART에서 기업 개요(업종, 설립일, 사업 요약, 연혁)를 가져와 저장한다 (Task 019).

    securities.corp_code -> DART company.json (기업개황)
                         -> DART list.json    (최신 사업보고서 접수번호)
                         -> DART document.xml (본문에서 '사업의 개요'와 '연혁' 발췌)
                         -> company_profiles upsert

단계 분리:
    parse_company_fields  : company.json 응답 정리 (순수 함수)
    build_profile         : 기업개황 + 보고서 본문 -> CompanyProfile (순수 함수)
    import_company_profiles: 종목별로 위를 호출하고 저장하는 진입점 (네트워크)

처리 규칙:
    * 종목마다 즉시 저장하므로 중간에 멈춰도 다시 실행하면 이어서 한다
      (이미 저장된 종목은 --refresh가 없으면 건너뛴다).
    * 사업보고서 본문을 읽지 못해도(없거나 형식이 달라도) 기업개황만으로 저장한다.
      단, 보고서를 내려받다가 오류가 났을 때는 저장하지 않는다. 일시적인 오류로
      본문 없는 행이 남아 다시 시도되지 않는 것을 막기 위해서다.
    * 요청 한도 초과(status 020)가 나면 즉시 멈춘다.

실행 방법:
    uv run python -m quantpublisher.crawler.company_profile_import --limit 5
    uv run python -m quantpublisher.crawler.company_profile_import --codes 005930 000660
    uv run python -m quantpublisher.crawler.company_profile_import            # 전체
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from config.settings import Settings, get_settings
from quantpublisher.crawler.dart_client import (
    AnnualReportRef,
    DartApiError,
    DartClient,
    DartError,
    DartRateLimitError,
)
from quantpublisher.crawler.dart_report_parser import (
    HistoryItem,
    extract_business_summary,
    extract_history,
)
from quantpublisher.database.company_profile_repository import CompanyProfileRepository
from quantpublisher.database.core import Database, init_db
from quantpublisher.database.models import CompanyProfile
from quantpublisher.database.security_repository import SecurityRepository

logger = logging.getLogger(__name__)

_CORP_CODE_PATTERN = re.compile(r"^\d{8}$")
_STATUS_NO_DOCUMENT = "014"  # document.xml: 파일이 존재하지 않습니다


@dataclass(slots=True)
class CompanyImportResult:
    """기업 개요 수집 결과 요약."""

    targets: int = 0
    requested: int = 0
    saved: int = 0
    skipped_existing: int = 0
    no_company_data: int = 0
    failed: int = 0
    with_report: int = 0
    with_summary: int = 0
    with_history: int = 0
    rate_limited: bool = False
    failed_codes: list[str] = field(default_factory=list)


def parse_company_fields(company: dict[str, Any]) -> dict[str, Any]:
    """company.json 응답에서 저장할 필드를 정리한다 (순수 함수).

    빈 문자열, 형식이 틀린 설립일/결산월은 None으로 둔다.
    """
    return {
        "induty_code": _clean_digits(company.get("induty_code")),
        "established_date": _parse_dart_date(company.get("est_dt")),
        "ceo_name": _clean_text(company.get("ceo_nm")),
        "address": _clean_text(company.get("adres")),
        "homepage": _clean_text(company.get("hm_url")),
        "fiscal_month": _parse_month(company.get("acc_mt")),
    }


def build_profile(
    stock_code: str,
    company: dict[str, Any],
    report: AnnualReportRef | None = None,
    report_xml: str | None = None,
) -> CompanyProfile:
    """기업개황과 (있다면) 사업보고서 본문으로 CompanyProfile을 만든다 (순수 함수)."""
    summary = extract_business_summary(report_xml) if report_xml else None
    history = extract_history(report_xml) if report_xml else []
    return CompanyProfile(
        stock_code=stock_code,
        **parse_company_fields(company),
        business_summary=summary,
        history_json=_history_to_json(history),
        report_rcept_no=report.rcept_no if report is not None else None,
        report_year=report.fiscal_year if report is not None else None,
    )


def import_company_profiles(
    connection: sqlite3.Connection,
    client: DartClient,
    stock_codes: Sequence[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
    fetch_reports: bool = True,
) -> CompanyImportResult:
    """종목별로 DART에서 기업 개요를 가져와 저장한다.

    Args:
        connection: 쓰기 가능한 DB 연결.
        client: DART 클라이언트.
        stock_codes: 지정하면 이 종목만 대상으로 한다. 없으면 corp_code가 있는 활성 종목 전체.
        limit: 이번 실행에서 새로 처리할 최대 종목 수.
        refresh: True면 이미 저장된 종목도 다시 가져온다.
        fetch_reports: False면 사업보고서 본문을 받지 않고 기업개황만 저장한다 (종목당 1건 호출).
    """
    repository = CompanyProfileRepository(connection)
    done = set() if refresh else repository.list_stock_codes()
    result = CompanyImportResult()

    targets = _select_targets(connection, stock_codes)
    result.targets = len(targets)
    if not targets:
        logger.warning(
            "company_import_no_targets reason=corp_code가 있는 활성 종목이 없거나 --codes와 일치하는 종목이 없습니다 "
            "codes_given=%s",
            len(stock_codes) if stock_codes else 0,
        )
    started = time.monotonic()
    for stock_code, corp_code in targets:
        if stock_code in done:
            result.skipped_existing += 1
            continue
        if limit is not None and result.requested >= limit:
            break
        result.requested += 1
        try:
            profile = _fetch_profile(client, stock_code, corp_code, fetch_reports)
        except DartRateLimitError:
            logger.error("company_import_rate_limited stock_code=%s", stock_code)
            result.rate_limited = True
            break
        except DartError as exc:
            logger.warning("company_import_failed stock_code=%s reason=%s", stock_code, exc)
            result.failed += 1
            result.failed_codes.append(stock_code)
            continue
        if profile is None:
            result.no_company_data += 1
            continue
        repository.upsert(profile)
        result.saved += 1
        result.with_report += profile.report_rcept_no is not None
        result.with_summary += profile.business_summary is not None
        result.with_history += profile.history_json is not None
        if result.requested % 50 == 0:
            logger.info(
                "company_import_progress requested=%d saved=%d elapsed_seconds=%.0f",
                result.requested,
                result.saved,
                time.monotonic() - started,
            )
    return result


def _fetch_profile(
    client: DartClient, stock_code: str, corp_code: str, fetch_reports: bool
) -> CompanyProfile | None:
    company = client.get_company(corp_code)
    if company is None:
        return None
    report = client.find_latest_annual_report(corp_code) if fetch_reports else None
    xml = None
    if report is not None:
        try:
            xml = client.fetch_report_xml(report.rcept_no)
        except DartApiError as exc:
            if exc.status != _STATUS_NO_DOCUMENT:
                raise
            # 공시는 있지만 원문 파일이 제공되지 않는 경우(일부 금융지주 등). 본문 없이 저장한다.
            logger.info("company_import_no_document stock_code=%s", stock_code)
    return build_profile(stock_code, company, report, xml)


def _select_targets(
    connection: sqlite3.Connection, stock_codes: Sequence[str] | None
) -> list[tuple[str, str]]:
    """(종목코드, corp_code) 목록. corp_code가 없거나 형식이 틀린 종목은 제외한다."""
    wanted = set(stock_codes) if stock_codes else None
    targets = []
    for security in SecurityRepository(connection).list_all(active_only=True):
        if wanted is not None and security.stock_code not in wanted:
            continue
        if security.corp_code and _CORP_CODE_PATTERN.match(security.corp_code):
            targets.append((security.stock_code, security.corp_code))
    return targets


def _history_to_json(history: Sequence[HistoryItem]) -> str | None:
    if not history:
        return None
    return json.dumps([[item.year, item.text] for item in history], ensure_ascii=False)


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _clean_digits(value: Any) -> str | None:
    text = _clean_text(value)
    return text if text and text.isdigit() else None


def _parse_dart_date(value: Any) -> str | None:
    """"19690113" -> "1969-01-13". 형식이 틀리거나 없는 날짜면 None."""
    text = _clean_text(value)
    if not text or not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _parse_month(value: Any) -> int | None:
    text = _clean_text(value)
    if not text or not text.isdigit():
        return None
    month = int(text)
    return month if 1 <= month <= 12 else None


def _configure_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(settings.log_dir / "company_profile_import.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점. 종료 코드: 0 성공 / 1 중단(설정 오류, 한도 초과) / 2 일부 종목 실패."""
    parser = argparse.ArgumentParser(description="DART 기업 개요 수집 (Task 019)")
    parser.add_argument("--codes", nargs="+", help="이 종목코드만 처리")
    parser.add_argument("--limit", type=int, help="이번 실행에서 새로 처리할 최대 종목 수")
    parser.add_argument("--refresh", action="store_true", help="이미 저장된 종목도 다시 가져오기")
    parser.add_argument(
        "--no-report", action="store_true", help="사업보고서 본문 없이 기업개황만 가져오기"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    _configure_logging(settings)
    if settings.dart_api_key is None:
        logger.error("company_import_aborted reason=QP_DART_API_KEY가 설정되지 않았습니다")
        return 1

    init_db(settings.db_path)
    client = DartClient(settings.dart_api_key)
    with Database(settings.db_path).connect() as connection:
        result = import_company_profiles(
            connection,
            client,
            stock_codes=args.codes,
            limit=args.limit,
            refresh=args.refresh,
            fetch_reports=not args.no_report,
        )
    logger.info(
        "company_import_summary targets=%d requested=%d saved=%d skipped_existing=%d "
        "no_company_data=%d failed=%d with_report=%d with_summary=%d with_history=%d "
        "rate_limited=%s",
        result.targets,
        result.requested,
        result.saved,
        result.skipped_existing,
        result.no_company_data,
        result.failed,
        result.with_report,
        result.with_summary,
        result.with_history,
        result.rate_limited,
    )
    if result.failed_codes:
        logger.error("company_import_failed_codes codes=%s", result.failed_codes)
    if result.rate_limited:
        return 1
    return 2 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
