"""외부 Mac mini의 quant.db에서 가격/종목 마스터/재무 데이터를 가져오는 진입점 (Task 013).

외부 quant.db(가격/종목/재무 통합 DB)를 .backup 스냅샷으로 한 번 복사한 뒤, 그 파일로:
    1. 가격: v_adj_price(수정주가) -> 파싱/검증 -> prices_daily upsert
    2. corp_code: stock -> securities.corp_code
    3. 재무/밸류에이션 (Task 014): financial_q(결산월 분기) -> financial_statements,
       quant_latest -> financial_metrics(최신 월)

외부 접속이 실패하면 DB에 아무것도 쓰기 전에 예외로 끝난다 (기존 prices_daily 불변).

실행:
    uv run python -m quantpublisher.crawler.market_data_import [--full-prices]
    --full-prices: 가격을 증분이 아니라 원천 전체 기간으로 다시 가져와 덮어쓴다.
종료 코드: 0 성공 / 1 중단(접속 실패 등)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from config.settings import Settings, get_settings
from quantpublisher.crawler.corp_code_import import (
    CorpCodeImportResult,
    StockTableReadError,
    import_corp_codes,
)
from quantpublisher.crawler.external_mac import (
    ExternalDataSource,
    ExternalMacClient,
    ExternalSourceError,
)
from quantpublisher.crawler.financial_import import (
    FinancialDataReadError,
    FinancialImportResult,
    import_financial_data,
)
from quantpublisher.crawler.price_import import (
    PriceDataReadError,
    PriceParseStats,
    find_readjusted_codes,
    parse_price_rows,
    read_price_rows,
    read_source_first_dates,
    save_prices,
)
from quantpublisher.database.core import Database, init_db
from quantpublisher.database.price_repository import PriceRepository
from quantpublisher.database.security_repository import SecurityRepository

logger = logging.getLogger(__name__)

_STAGING_RELATIVE_DIR = Path("raw") / "external"
_LOG_SAMPLE_SIZE = 10


class MarketDataImportError(Exception):
    """가져오기를 시작할 수 없거나 계속할 수 없는 오류."""


@dataclass(frozen=True, slots=True)
class PriceImportResult:
    """가격 가져오기 결과.

    Attributes:
        stocks_requested: 원천 daily_price에 일봉이 있어 읽기를 요청한 종목 수.
        stocks_missing_source: securities에는 있으나 원천 daily_price에 없는 종목 수.
        source_codes_not_in_securities: 원천에는 있으나 securities에 없어 가져오지 않은 종목 수.
        rows_received: 원천에서 읽은 행 수.
        rows_saved: prices_daily에 upsert한 행 수.
        rows_skipped_unknown_code: securities에 없는 종목코드 행 (건너뜀).
        rows_skipped_invalid: 형식/범위 검증 실패 행 (건너뜀).
        full_refresh: 증분이 아니라 전체 기간을 다시 가져왔는지 여부.
        stocks_readjusted: 증분 모드에서 수정주가가 재보정돼 전체를 다시 가져온 종목 수.
    """

    stocks_requested: int
    stocks_missing_source: int
    source_codes_not_in_securities: int
    rows_received: int
    rows_saved: int
    rows_skipped_unknown_code: int
    rows_skipped_invalid: int
    full_refresh: bool = False
    stocks_readjusted: int = 0


@dataclass(frozen=True, slots=True)
class MarketDataImportResult:
    """전체 가져오기 결과."""

    prices: PriceImportResult
    corp_codes: CorpCodeImportResult
    elapsed_seconds: float
    financial: FinancialImportResult | None = None


def import_prices(
    connection: sqlite3.Connection, quant_db_path: Path, full_refresh: bool = False
) -> PriceImportResult:
    """quant.db 스냅샷의 수정주가(v_adj_price)를 prices_daily로 가져온다.

    기본은 증분이다. 종목별 기준은 prices_daily에 저장된 MAX(trade_date)이고, 저장된
    행이 없는 종목은 전체를 가져온다. 분할/병합/감자로 과거 수정주가가 바뀐 종목
    (원천 첫 거래일의 저장된 종가가 원천과 다름)은 증분이 아니라 전체를 다시 가져온다.
    full_refresh면 모든 종목을 전체 기간으로 다시 가져와 같은 날짜의 값을 원천 값으로
    덮어쓴다 (원천을 바꿨을 때 한 번 실행).

    Raises:
        MarketDataImportError: securities가 비어 있는 경우.
        PriceDataReadError: 스냅샷의 daily_price를 읽을 수 없는 경우.
    """
    known_codes = {s.stock_code for s in SecurityRepository(connection).list_all()}
    if not known_codes:
        raise MarketDataImportError(
            "securities가 비어 있습니다. 먼저 종목 목록을 수집하세요 "
            "(python -m quantpublisher.automation.daily_update)."
        )

    source_first_dates = read_source_first_dates(quant_db_path)
    source_codes = set(source_first_dates)
    target_codes = sorted(known_codes & source_codes)
    missing_source = sorted(known_codes - source_codes)
    not_in_securities = sorted(source_codes - known_codes)
    if missing_source:
        logger.warning(
            "price_source_missing count=%d sample=%s",
            len(missing_source),
            missing_source[:_LOG_SAMPLE_SIZE],
        )
    if not_in_securities:
        logger.warning(
            "price_source_codes_not_in_securities skipped count=%d sample=%s",
            len(not_in_securities),
            not_in_securities[:_LOG_SAMPLE_SIZE],
        )

    readjusted: set[str] = set()
    if full_refresh:
        since_by_code: dict[str, str | None] = {code: None for code in target_codes}
    else:
        repository = PriceRepository(connection)
        latest_dates = repository.get_latest_trade_dates()
        stored_closes = repository.get_closes_on(
            {code: source_first_dates[code] for code in target_codes}
        )
        readjusted = find_readjusted_codes(quant_db_path, stored_closes)
        if readjusted:
            logger.info(
                "price_readjusted_full_refresh count=%d sample=%s",
                len(readjusted),
                sorted(readjusted)[:_LOG_SAMPLE_SIZE],
            )
        since_by_code = {
            code: None if code in readjusted else latest_dates.get(code)
            for code in target_codes
        }

    stats = PriceParseStats()
    saved = save_prices(
        connection,
        parse_price_rows(read_price_rows(quant_db_path, since_by_code), known_codes, stats),
    )

    logger.info(
        "prices_imported requested=%d full_refresh=%s readjusted=%d received=%d saved=%d "
        "skipped_unknown_code=%d skipped_invalid=%d",
        len(target_codes),
        full_refresh,
        len(readjusted),
        stats.received,
        saved,
        stats.skipped_unknown_code,
        stats.skipped_invalid,
    )
    return PriceImportResult(
        stocks_requested=len(target_codes),
        stocks_missing_source=len(missing_source),
        source_codes_not_in_securities=len(not_in_securities),
        rows_received=stats.received,
        rows_saved=saved,
        rows_skipped_unknown_code=stats.skipped_unknown_code,
        rows_skipped_invalid=stats.skipped_invalid,
        full_refresh=full_refresh,
        stocks_readjusted=len(readjusted),
    )


def collect_market_data(
    connection: sqlite3.Connection,
    source: ExternalDataSource,
    staging_dir: Path,
    full_refresh_prices: bool = False,
) -> MarketDataImportResult:
    """quant.db 스냅샷을 한 번 복사한 뒤 가격, corp_code, 재무/밸류에이션을 반영한다.

    외부 접근(스냅샷 복사)은 DB 쓰기보다 먼저 끝난다. 재무 데이터는 securities에
    있는 종목만 저장하므로 corp_code와의 순서는 중요하지 않다.
    """
    started_at = time.monotonic()
    quant_dir = _prepare_staging_dir(staging_dir / "quant")
    quant_db_path = source.fetch_quant_db(quant_dir)
    prices = import_prices(connection, quant_db_path, full_refresh=full_refresh_prices)
    corp_codes = import_corp_codes(connection, quant_db_path)
    financial = import_financial_data(connection, quant_db_path)
    return MarketDataImportResult(
        prices=prices,
        corp_codes=corp_codes,
        elapsed_seconds=time.monotonic() - started_at,
        financial=financial,
    )


def _prepare_staging_dir(path: Path) -> Path:
    """이전 실행의 중간 파일이 섞이지 않도록 비운 디렉터리를 만든다."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _configure_logging(settings: Settings) -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(settings.log_dir / "market_data_import.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 종료 코드: 0 성공 / 1 중단."""
    parser = argparse.ArgumentParser(description="외부 quant.db에서 가격/재무 데이터를 가져온다.")
    parser.add_argument(
        "--full-prices",
        action="store_true",
        help="가격을 증분이 아니라 원천 전체 기간으로 다시 가져와 덮어쓴다.",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    _configure_logging(settings)
    if settings.external_mac is None:
        logger.error(
            "market_data_import_aborted reason=QP_EXTERNAL_HOST 등 외부 Mac 설정이 없습니다 "
            "(docs/MARKET_DATA_IMPORT.md 참고)"
        )
        return 1

    init_db(settings.db_path)  # prices_daily/financial_* 테이블과 securities.corp_code 컬럼 보장
    source = ExternalMacClient(settings.external_mac)
    staging_dir = settings.data_dir / _STAGING_RELATIVE_DIR
    try:
        with Database(settings.db_path).connect() as connection:
            result = collect_market_data(
                connection, source, staging_dir, full_refresh_prices=args.full_prices
            )
    except (
        ExternalSourceError,
        PriceDataReadError,
        StockTableReadError,
        FinancialDataReadError,
        MarketDataImportError,
    ) as exc:
        logger.error("market_data_import_aborted reason=%s", exc)
        return 1

    logger.info(
        "market_data_import_summary stocks_requested=%d full_refresh=%s rows_saved=%d "
        "corp_codes_updated=%d elapsed_seconds=%.2f",
        result.prices.stocks_requested,
        result.prices.full_refresh,
        result.prices.rows_saved,
        result.corp_codes.updated,
        result.elapsed_seconds,
    )
    if result.financial is not None:
        logger.info(
            "financial_import_summary statements_saved=%d net_income_nullified=%d "
            "sales_nullified=%d metrics_saved=%d per_pbr_nullified=%d",
            result.financial.statements_saved,
            result.financial.net_income_nullified,
            result.financial.sales_nullified,
            result.financial.metrics_saved,
            result.financial.per_pbr_nullified,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
