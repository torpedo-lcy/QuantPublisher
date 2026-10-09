"""외부 Mac mini의 가격/종목 마스터 데이터를 가져오는 진입점 (Task 013).

흐름:
    1. 가격: 외부 stock-price/<종목코드>.db의 daily -> 파싱/검증 -> prices_daily upsert
    2. corp_code: 외부 quant.db(.backup 스냅샷)의 stock_master -> securities.corp_code
    3. 재무/밸류에이션 (Task 014): 같은 quant.db 스냅샷의 financial_data(연간) ->
       financial_statements, market_data -> financial_metrics

외부 접속이 실패하면 DB에 아무것도 쓰기 전에 예외로 끝난다 (기존 prices_daily 불변).
종목 하나가 원격에서 추출 실패해도 나머지는 계속 처리하고, 실패 종목 수를 결과에
포함한다.

실행:
    uv run python -m quantpublisher.crawler.market_data_import
종료 코드: 0 성공 / 1 중단(접속 실패 등) / 2 일부 종목 실패
"""

from __future__ import annotations

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
    StockMasterReadError,
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
from quantpublisher.crawler.price_import import PriceParseStats, parse_price_lines, save_prices
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
        stocks_requested: 원격에 가격 DB가 있어 추출을 요청한 종목 수.
        stocks_failed: 원격 추출이 실패한 종목 수.
        failed_codes: 실패한 종목코드 (정렬).
        stocks_missing_remote: securities에는 있으나 원격 가격 DB가 없는 종목 수.
        remote_files_not_in_securities: 원격에는 있으나 securities에 없어 가져오지 않은 파일 수.
        rows_received: 받은 PSV 행 수.
        rows_saved: prices_daily에 upsert한 행 수.
        rows_skipped_unknown_code: securities에 없는 종목코드 행 (건너뜀).
        rows_skipped_invalid: 형식/범위 검증 실패 행 (건너뜀).
    """

    stocks_requested: int
    stocks_failed: int
    failed_codes: tuple[str, ...]
    stocks_missing_remote: int
    remote_files_not_in_securities: int
    rows_received: int
    rows_saved: int
    rows_skipped_unknown_code: int
    rows_skipped_invalid: int


@dataclass(frozen=True, slots=True)
class MarketDataImportResult:
    """전체 가져오기 결과."""

    prices: PriceImportResult
    corp_codes: CorpCodeImportResult
    elapsed_seconds: float
    financial: FinancialImportResult | None = None


def import_prices(
    connection: sqlite3.Connection, source: ExternalDataSource, staging_dir: Path
) -> PriceImportResult:
    """외부 가격 DB를 prices_daily로 가져온다 (최초 백필 + 이후 증분).

    종목별 증분 기준은 prices_daily에 저장된 MAX(trade_date)이고, 저장된 행이 없는
    종목은 전체를 가져온다. 외부 접근(예외 발생 가능)은 DB 쓰기보다 먼저 끝난다.

    Raises:
        MarketDataImportError: securities가 비어 있는 경우.
        ExternalSourceError: 외부 Mac 접속/명령/전송 실패.
    """
    known_codes = {s.stock_code for s in SecurityRepository(connection).list_all()}
    if not known_codes:
        raise MarketDataImportError(
            "securities가 비어 있습니다. 먼저 종목 목록을 수집하세요 "
            "(python -m quantpublisher.automation.daily_update)."
        )

    remote_codes = set(source.list_price_stock_codes())
    target_codes = sorted(known_codes & remote_codes)
    missing_remote = sorted(known_codes - remote_codes)
    not_in_securities = sorted(remote_codes - known_codes)
    if missing_remote:
        logger.warning(
            "price_remote_db_missing count=%d sample=%s",
            len(missing_remote),
            missing_remote[:_LOG_SAMPLE_SIZE],
        )
    if not_in_securities:
        logger.warning(
            "price_remote_files_not_in_securities skipped count=%d sample=%s",
            len(not_in_securities),
            not_in_securities[:_LOG_SAMPLE_SIZE],
        )

    latest_dates = PriceRepository(connection).get_latest_trade_dates()
    since_by_code = {code: latest_dates.get(code) for code in target_codes}

    dest_dir = _prepare_staging_dir(staging_dir / "prices")
    export = source.export_prices(since_by_code, dest_dir)

    stats = PriceParseStats()
    with export.psv_path.open("r", encoding="utf-8") as psv_file:
        saved = save_prices(connection, parse_price_lines(psv_file, known_codes, stats))

    for code, message in sorted(export.failures.items()):
        logger.error("price_export_failed stock_code=%s reason=%s", code, message)
    logger.info(
        "prices_imported requested=%d failed=%d received=%d saved=%d "
        "skipped_unknown_code=%d skipped_invalid=%d",
        len(target_codes),
        len(export.failures),
        stats.received,
        saved,
        stats.skipped_unknown_code,
        stats.skipped_invalid,
    )
    return PriceImportResult(
        stocks_requested=len(target_codes),
        stocks_failed=len(export.failures),
        failed_codes=tuple(sorted(export.failures)),
        stocks_missing_remote=len(missing_remote),
        remote_files_not_in_securities=len(not_in_securities),
        rows_received=stats.received,
        rows_saved=saved,
        rows_skipped_unknown_code=stats.skipped_unknown_code,
        rows_skipped_invalid=stats.skipped_invalid,
    )


def collect_market_data(
    connection: sqlite3.Connection, source: ExternalDataSource, staging_dir: Path
) -> MarketDataImportResult:
    """가격을 가져온 뒤, quant.db 스냅샷 하나로 corp_code와 재무/밸류에이션을 반영한다.

    corp_code를 먼저 반영하고 재무/밸류에이션을 가져온다. 재무 데이터는 securities에
    있는 종목만 저장하므로 순서는 중요하지 않지만, 스냅샷은 한 번만 복사한다.
    """
    started_at = time.monotonic()
    prices = import_prices(connection, source, staging_dir)
    quant_dir = _prepare_staging_dir(staging_dir / "quant")
    quant_db_path = source.fetch_quant_db(quant_dir)
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


def main() -> int:
    """CLI 진입점. 종료 코드: 0 성공 / 1 중단 / 2 일부 종목 실패."""
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
            result = collect_market_data(connection, source, staging_dir)
    except (
        ExternalSourceError,
        StockMasterReadError,
        FinancialDataReadError,
        MarketDataImportError,
    ) as exc:
        logger.error("market_data_import_aborted reason=%s", exc)
        return 1

    logger.info(
        "market_data_import_summary stocks_requested=%d stocks_failed=%d rows_saved=%d "
        "corp_codes_updated=%d elapsed_seconds=%.2f",
        result.prices.stocks_requested,
        result.prices.stocks_failed,
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
    if result.prices.stocks_failed:
        logger.error("market_data_import_partial_failure failed_codes=%s", result.prices.failed_codes)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
