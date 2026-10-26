"""quant.db 스냅샷의 수정주가(v_adj_price) 가져오기 테스트 (fixture 기반, 외부 접속 없음)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from subprocess import CompletedProcess
from typing import Iterator

import pytest

from config.settings import ExternalMacSettings
from quantpublisher.crawler.external_mac import ExternalCommandError, ExternalMacClient
from quantpublisher.crawler.market_data_import import import_prices
from quantpublisher.crawler.price_import import (
    PriceDataReadError,
    PriceParseStats,
    find_readjusted_codes,
    parse_price_rows,
    read_price_rows,
)
from quantpublisher.database.connection import get_connection, initialize_schema
from quantpublisher.database.models import PriceDaily, Security
from quantpublisher.database.price_repository import PriceRepository
from quantpublisher.database.security_repository import SecurityRepository

_DAILY_PRICE_SCHEMA = """
CREATE TABLE daily_price (
    code TEXT NOT NULL, date INTEGER NOT NULL,
    open INTEGER, high INTEGER, low INTEGER, close INTEGER NOT NULL,
    volume INTEGER, value INTEGER,
    PRIMARY KEY (code, date)
) WITHOUT ROWID;
CREATE TABLE corp_event (
    code TEXT NOT NULL, date INTEGER NOT NULL, kind TEXT NOT NULL, ratio REAL, note TEXT,
    PRIMARY KEY (code, date, kind)
);
CREATE VIEW v_adj_price AS SELECT code, date, open, high, low, close, volume, value, adj_factor,
    open * adj_factor AS adj_open, high * adj_factor AS adj_high, low * adj_factor AS adj_low,
    close * adj_factor AS adj_close
FROM (SELECT p.*, COALESCE((SELECT exp(sum(ln(e.ratio))) FROM corp_event e
    WHERE e.code = p.code AND e.date > p.date AND e.ratio > 0
      AND e.kind IN ('REV_SPLIT', 'BONUS', 'CAP_DECREASE')), 1.0) AS adj_factor
FROM daily_price p);
"""


def _make_quant_db(path: Path, rows: list[tuple], events: list[tuple] | None = None) -> Path:
    """daily_price(원주가) 행과 corp_event((code, date, kind, ratio)) 행으로 원천을 만든다."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_DAILY_PRICE_SCHEMA)
        connection.executemany(
            "INSERT INTO daily_price (code, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO corp_event (code, date, kind, ratio) VALUES (?, ?, ?, ?)", events or []
        )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_connection(tmp_path / "test.sqlite3")
    initialize_schema(conn)
    repository = SecurityRepository(conn)
    repository.upsert(Security(stock_code="005930", name="Samsung Electronics", market="KOSPI"))
    repository.upsert(Security(stock_code="000660", name="SK hynix", market="KOSPI"))
    yield conn
    conn.close()


# ── 파싱/검증 ───────────────────────────────────────────────────────────


def test_parse_price_rows_converts_integer_date_and_rejects_bad_rows() -> None:
    stats = PriceParseStats()

    parsed = list(
        parse_price_rows(
            [
                ("005930", 20261026, 213500, 216000, 211500, 213500, 11376006),  # 정상
                ("005930", 20261027, 0, 0, 0, 213500, 0),  # 거래정지일 0은 허용
                ("005930", 20261332, 1, 1, 1, 1, 1),  # 없는 날짜
                ("005930", "20261028", 1, 1, 1, 1, 1),  # 정수 아님
                ("005930", 20261029, None, 1, 1, 1, 1),  # 시가 없음
                ("005930", 20261030, 1, 1, 1, -1, 1),  # 음수 종가
                ("005930", 20261031, 1, 1, 1, 1),  # 필드 수 부족
                ("999999", 20261026, 1, 1, 1, 1, 1),  # securities에 없음
            ],
            {"005930"},
            stats,
        )
    )

    assert [p.trade_date for p in parsed] == ["2026-10-26", "2026-10-27"]
    assert parsed[0].close == 213500.0
    assert stats.received == 8
    assert stats.skipped_invalid == 5
    assert stats.skipped_unknown_code == 1


def test_read_price_rows_reads_only_after_since_in_date_order(tmp_path: Path) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [
            ("005930", 20261023, 1, 1, 1, 3, 1),
            ("005930", 20261021, 1, 1, 1, 1, 1),
            ("005930", 20261022, 1, 1, 1, 2, 1),
            ("000660", 20261021, 1, 1, 1, 9, 1),
        ],
    )

    rows = list(read_price_rows(quant_db, {"005930": "2026-10-21", "000660": None}))

    assert [(r[0], r[1]) for r in rows] == [
        ("000660", 20261021),
        ("005930", 20261022),
        ("005930", 20261023),
    ]


def test_read_price_rows_rejects_malformed_since(tmp_path: Path) -> None:
    quant_db = _make_quant_db(tmp_path / "quant.db", [])

    with pytest.raises(PriceDataReadError):
        list(read_price_rows(quant_db, {"005930": "20261021"}))


def test_read_price_rows_returns_split_adjusted_prices_and_volume(tmp_path: Path) -> None:
    # 2026-10-23에 5:1 병합(REV_SPLIT ratio 5): 그 이전 가격은 x5, 거래량은 /5
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [
            ("005930", 20261022, 100, 110, 90, 100, 5000),
            ("005930", 20261023, 500, 550, 450, 500, 1000),
        ],
        [("005930", 20261023, "REV_SPLIT", 5.0), ("005930", 20261020, "LOCK", None)],
    )

    rows = list(read_price_rows(quant_db, {"005930": None}))

    assert rows[0][1:] == (20261022, 500.0, 550.0, 450.0, 500.0, 1000.0)
    assert rows[1][1:] == (20261023, 500.0, 550.0, 450.0, 500.0, 1000.0)


def test_find_readjusted_codes_detects_changed_adjusted_close(tmp_path: Path) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [("005930", 20261022, 1, 1, 1, 100, 1), ("000660", 20261022, 1, 1, 1, 100, 1)],
        [("005930", 20261023, "REV_SPLIT", 5.0)],
    )

    readjusted = find_readjusted_codes(
        quant_db,
        {
            "005930": ("2026-10-22", 100.0),  # 병합 전에 저장한 값: 원천은 이제 500
            "000660": ("2026-10-22", 100.0),  # 그대로
        },
    )

    assert readjusted == {"005930"}


# ── 증분 / 전체 덮어쓰기 ────────────────────────────────────────────────


def test_import_prices_is_incremental_from_latest_stored_date(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    PriceRepository(connection).upsert_many(
        [PriceDaily("005930", "2026-10-22", 1.0, 1.0, 1.0, 262000.0, 999.0)]
    )
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [
            ("005930", 20261022, 1, 1, 1, 262000, 1),  # 저장된 날짜: 증분이면 건드리지 않음
            ("005930", 20261023, 1, 1, 1, 213500, 1),
            ("000660", 20261023, 1, 1, 1, 500000, 1),  # 저장된 행이 없으면 전체
        ],
    )

    result = import_prices(connection, quant_db)

    stored = PriceRepository(connection).list_by_code("005930")
    prices = {p.trade_date: (p.close, p.volume) for p in stored}
    assert prices == {"2026-10-22": (262000.0, 999.0), "2026-10-23": (213500.0, 1.0)}
    assert result.stocks_readjusted == 0
    assert len(PriceRepository(connection).list_by_code("000660")) == 1
    assert result.rows_saved == 2
    assert result.full_refresh is False


def test_import_prices_full_refresh_overwrites_stored_dates_with_source_values(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    PriceRepository(connection).upsert_many(
        [PriceDaily("005930", "2026-10-22", 1.0, 1.0, 1.0, 263500.0, 1.0)]
    )
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [("005930", 20261021, 1, 1, 1, 260000, 1), ("005930", 20261022, 1, 1, 1, 262000, 1)],
    )

    result = import_prices(connection, quant_db, full_refresh=True)

    prices = {p.trade_date: p.close for p in PriceRepository(connection).list_by_code("005930")}
    assert prices == {"2026-10-21": 260000.0, "2026-10-22": 262000.0}
    assert result.rows_saved == 2
    assert result.full_refresh is True


def test_import_prices_refetches_whole_history_when_new_split_readjusts_past_prices(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    before = _make_quant_db(
        tmp_path / "before.db",
        [("005930", 20261021, 1, 1, 1, 100, 10), ("005930", 20261022, 1, 1, 1, 110, 10)],
    )
    import_prices(connection, before)
    # 다음 날 5:1 병합이 생겨 이전 날짜의 수정주가가 모두 바뀐다
    after = _make_quant_db(
        tmp_path / "after.db",
        [
            ("005930", 20261021, 1, 1, 1, 100, 10),
            ("005930", 20261022, 1, 1, 1, 110, 10),
            ("005930", 20261023, 5, 5, 5, 560, 2),
        ],
        [("005930", 20261023, "REV_SPLIT", 5.0)],
    )

    result = import_prices(connection, after)

    prices = {p.trade_date: p.close for p in PriceRepository(connection).list_by_code("005930")}
    assert prices == {"2026-10-21": 500.0, "2026-10-22": 550.0, "2026-10-23": 560.0}
    assert result.stocks_readjusted == 1
    assert result.rows_saved == 3


def test_import_prices_counts_codes_missing_from_source_and_not_in_securities(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    quant_db = _make_quant_db(
        tmp_path / "quant.db",
        [("005930", 20261023, 1, 1, 1, 1, 1), ("123456", 20261023, 1, 1, 1, 1, 1)],
    )

    result = import_prices(connection, quant_db)

    assert result.stocks_requested == 1
    assert result.stocks_missing_source == 1  # 000660
    assert result.source_codes_not_in_securities == 1  # 123456 (요청하지 않음)
    assert result.rows_skipped_unknown_code == 0


def test_import_prices_raises_when_daily_price_table_is_missing(
    connection: sqlite3.Connection, tmp_path: Path
) -> None:
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()

    with pytest.raises(PriceDataReadError):
        import_prices(connection, empty)


# ── 외부 Mac 스냅샷 ─────────────────────────────────────────────────────


def test_fetch_quant_db_quotes_remote_path_and_pulls_snapshot(tmp_path: Path) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_runner(args, **kwargs):  # noqa: ANN001
        calls.append((args, kwargs.get("input")))
        if args[0] == "ssh" and args[-1] == "sh -s":
            return CompletedProcess(args, 0, stdout="/tmp/qp_quant.Ab12\n", stderr="")
        return CompletedProcess(args, 0, stdout="", stderr="")

    config = ExternalMacSettings(host="h", user=None, quant_db_path="/Users/home/my db/quant.db")
    client = ExternalMacClient(config, runner=fake_runner)

    path = client.fetch_quant_db(tmp_path / "quant")

    assert path == tmp_path / "quant" / "quant.db"
    script = calls[0][1]
    assert script is not None
    assert "DB='/Users/home/my db/quant.db'" in script
    assert "immutable=1" in script and "mode=ro" in script
    assert "PRAGMA journal_mode=DELETE" in script
    assert calls[1][0][0] == "rsync"
    assert calls[2][0][-1] == "rm -rf -- /tmp/qp_quant.Ab12"  # 원격 임시 디렉터리 정리


def test_fetch_quant_db_rejects_unexpected_remote_output(tmp_path: Path) -> None:
    def fake_runner(args, **kwargs):  # noqa: ANN001
        return CompletedProcess(args, 0, stdout="/etc\n", stderr="")

    config = ExternalMacSettings(host="h", user=None, quant_db_path="/q/quant.db")
    client = ExternalMacClient(config, runner=fake_runner)

    with pytest.raises(ExternalCommandError):
        client.fetch_quant_db(tmp_path / "quant")
