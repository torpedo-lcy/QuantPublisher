"""일일 데이터 갱신 자동화 진입점.

crawler -> database -> report 계층의 공개 API를 순서대로 호출한다
(ARCHITECTURE.md 11절: "각 작업을 순서대로 호출한다").

이 모듈 자체는 크롤링 파싱, 지표 계산, Markdown 렌더링 로직을 직접
구현하지 않는다. 각 계층에 이미 구현된 함수를 호출하고 orchestration과
로깅, 실패 처리만 담당한다.

실행 방법:
    uv run python -m quantpublisher.automation.daily_update

launchd를 통한 주기 실행 방법은 docs/AUTOMATION.md를 참고한다.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config.settings import PROJECT_ROOT, Settings, get_settings
from quantpublisher.crawler.krx_listing import KrxListingFetchError, collect_krx_listing
from quantpublisher.database.core import Database, init_db
from quantpublisher.database.models import Security
from quantpublisher.database.security_repository import SecurityRepository
from quantpublisher.automation.stock_metrics import load_stock_metrics
from quantpublisher.report import build_stock_report, write_stock_report_markdown

logger = logging.getLogger(__name__)

# website/content/stocks/ - Hugo가 그대로 콘텐츠로 인식하는 디렉터리.
_DEFAULT_CONTENT_RELATIVE_DIR = Path("website") / "content" / "stocks"


class DailyUpdateError(Exception):
    """daily_update 파이프라인 실행 중 발생한 오류.

    실제 원인 예외는 __cause__로 연결되어 상위 로그/호출자가 확인할 수
    있다. 오류를 숨기지 않는다 (DEVELOPMENT_RULE.md 6절).
    """


@dataclass(frozen=True, slots=True)
class DailyUpdateResult:
    """daily_update 실행 결과 요약."""

    securities_collected: int
    reports_generated: int
    elapsed_seconds: float


def run_daily_update(
    db_path: Path | None = None,
    content_dir: Path | None = None,
    settings: Settings | None = None,
) -> DailyUpdateResult:
    """crawler -> database -> report 파이프라인을 순서대로 실행한다.

    단계:
        1. init_db            : DB 스키마 초기화 (idempotent)
        2. collect_krx_listing: KRX 종목 목록 수집 및 securities 테이블 upsert
        3. 리포트 생성          : 등록된 활성 종목별로 financial_statements /
                                 financial_metrics를 조회해 지표를 계산하고
                                 Markdown 리포트 생성 (Task 015)

    이전 단계가 실패하면 다음 단계를 실행하지 않고 DailyUpdateError를
    발생시킨다 (ARCHITECTURE.md 12절: "crawler 실패 -> DB 업데이트 중단
    -> report 생성 중단 -> 오류 로그 기록").

    재무/밸류에이션 데이터는 이 함수가 수집하지 않는다. 별도로 실행한
    market_data_import(Task 013/014)가 저장해 둔 값을 읽기만 한다. 데이터가
    없는 종목은 해당 지표가 N/A로 표시되며 파이프라인은 정상 종료한다.

    Args:
        db_path: SQLite DB 경로. 지정하지 않으면 Settings.db_path 사용.
        content_dir: Markdown 리포트를 생성할 디렉터리 (Hugo content).
            지정하지 않으면 PROJECT_ROOT/website/content/stocks 사용.
        settings: 주입용 Settings. 지정하지 않으면 get_settings() 사용.

    Returns:
        DailyUpdateResult: 수집/생성 건수와 소요 시간.

    Raises:
        DailyUpdateError: 파이프라인의 어느 단계든 실패한 경우.
    """
    active_settings = settings if settings is not None else get_settings()
    resolved_db_path = db_path if db_path is not None else active_settings.db_path
    resolved_content_dir = (
        content_dir if content_dir is not None else PROJECT_ROOT / _DEFAULT_CONTENT_RELATIVE_DIR
    )

    started_at = time.monotonic()
    logger.info(
        "daily_update_started db_path=%s content_dir=%s",
        resolved_db_path,
        resolved_content_dir,
    )

    _initialize_database(resolved_db_path)

    database = Database(resolved_db_path)
    securities_collected = _collect_securities(database)
    reports_generated = _generate_reports(database, resolved_content_dir)

    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "daily_update_completed securities_collected=%d reports_generated=%d "
        "elapsed_seconds=%.2f",
        securities_collected,
        reports_generated,
        elapsed_seconds,
    )
    return DailyUpdateResult(
        securities_collected=securities_collected,
        reports_generated=reports_generated,
        elapsed_seconds=elapsed_seconds,
    )


def _initialize_database(db_path: Path) -> None:
    """DB 스키마를 초기화한다. 실패 시 DailyUpdateError로 변환한다."""
    try:
        init_db(db_path)
    except Exception as exc:
        logger.exception("daily_update_step_failed step=init_db")
        raise DailyUpdateError(f"DB 초기화에 실패했습니다: {exc}") from exc


def _collect_securities(database: Database) -> int:
    """KRX 종목 목록을 수집하여 저장한다. 실패 시 DailyUpdateError로 변환한다."""
    logger.info("daily_update_step_started step=collect_krx_listing source=KRX")
    try:
        with database.transaction() as connection:
            count = collect_krx_listing(connection)
    except KrxListingFetchError as exc:
        logger.exception("daily_update_step_failed step=collect_krx_listing source=KRX")
        raise DailyUpdateError(f"KRX 종목 목록 수집에 실패했습니다: {exc}") from exc
    except Exception as exc:
        logger.exception("daily_update_step_failed step=collect_krx_listing source=KRX")
        raise DailyUpdateError("KRX 종목 목록 수집 중 예기치 못한 오류가 발생했습니다.") from exc

    logger.info("daily_update_step_completed step=collect_krx_listing count=%d", count)
    return count


def _generate_reports(database: Database, content_dir: Path) -> int:
    """등록된 활성 종목에 대해 Markdown 리포트를 생성한다.

    실패 시 DailyUpdateError로 변환한다.
    """
    logger.info("daily_update_step_started step=generate_reports target=%s", content_dir)
    try:
        with database.connect() as connection:
            securities = SecurityRepository(connection).list_all(active_only=True)
            count = _write_reports(connection, securities, content_dir)
    except Exception as exc:
        logger.exception("daily_update_step_failed step=generate_reports")
        raise DailyUpdateError(f"리포트 생성 중 오류가 발생했습니다: {exc}") from exc

    logger.info("daily_update_step_completed step=generate_reports count=%d", count)
    return count


def _write_reports(
    connection: sqlite3.Connection,
    securities: Iterable[Security],
    content_dir: Path,
) -> int:
    """종목별 지표를 계산해 Markdown 리포트를 생성하고 파일 수를 반환한다.

    재무/밸류에이션 데이터가 없는 종목은 지표가 None(페이지에서 N/A)이다.
    DB 조회 오류는 숨기지 않고 상위로 전달한다 (불완전한 리포트를 만들지 않음).
    """
    count = 0
    with_statements = 0
    with_valuation = 0
    for security in securities:
        metrics, basis = load_stock_metrics(connection, security.stock_code)
        report = build_stock_report(security, metrics, basis=basis)
        write_stock_report_markdown(report, content_dir)
        count += 1
        with_statements += basis.statement_year is not None
        with_valuation += basis.valuation_month is not None
    logger.info(
        "report_metrics_coverage reports=%d with_statements=%d with_valuation=%d",
        count,
        with_statements,
        with_valuation,
    )
    return count


def _configure_logging(settings: Settings) -> None:
    """CLI 실행 시 파일/콘솔 로그 핸들러를 구성한다.

    라이브러리로 import되어 사용될 때는(run_daily_update 직접 호출)
    호출자의 로깅 설정을 그대로 따르도록 이 함수를 호출하지 않는다.
    """
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.log_dir / "daily_update.log"
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> int:
    """CLI 진입점.

    `uv run python -m quantpublisher.automation.daily_update`로 실행한다.

    Returns:
        성공하면 0, 실패하면 1.
    """
    settings = get_settings()
    _configure_logging(settings)
    try:
        result = run_daily_update(settings=settings)
    except DailyUpdateError as exc:
        logger.error("daily_update_aborted reason=%s", exc)
        return 1

    logger.info(
        "daily_update_summary securities_collected=%d reports_generated=%d "
        "elapsed_seconds=%.2f",
        result.securities_collected,
        result.reports_generated,
        result.elapsed_seconds,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
