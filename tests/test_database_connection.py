import sqlite3

import pytest

from quantpublisher.database import Database, init_db


def test_database_uses_settings_db_path_by_default(monkeypatch, tmp_path):
    from config.settings import get_settings

    monkeypatch.setenv("QP_DB_PATH", str(tmp_path / "settings_default.sqlite3"))
    get_settings.cache_clear()

    database = Database()

    assert database.db_path == tmp_path / "settings_default.sqlite3"

    get_settings.cache_clear()


def test_connect_creates_database_file(tmp_path):
    db_path = tmp_path / "nested" / "quantpublisher.sqlite3"
    database = Database(db_path)

    with database.connect():
        pass

    assert db_path.is_file()


def test_connect_returns_row_factory_and_enables_foreign_keys(tmp_path):
    database = Database(tmp_path / "quantpublisher.sqlite3")

    with database.connect() as conn:
        assert conn.row_factory is sqlite3.Row
        foreign_keys_enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert foreign_keys_enabled == 1


def test_connect_closes_connection_after_block(tmp_path):
    database = Database(tmp_path / "quantpublisher.sqlite3")

    with database.connect() as conn:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_transaction_commits_on_success(tmp_path):
    database = Database(tmp_path / "quantpublisher.sqlite3")

    with database.transaction() as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO sample (id) VALUES (1)")

    with database.connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM sample").fetchone()
        assert row[0] == 1


def test_transaction_rolls_back_on_exception(tmp_path):
    database = Database(tmp_path / "quantpublisher.sqlite3")

    with database.transaction() as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    with database.transaction() as conn:
        conn.execute("INSERT INTO sample (id) VALUES (1)")

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute("INSERT INTO sample (id) VALUES (2)")
            conn.execute("INSERT INTO sample (id) VALUES (2)")  # duplicate primary key

    with database.connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM sample").fetchone()
        assert row[0] == 1  # second transaction's insert was rolled back


def test_init_db_creates_parent_directory_and_file(tmp_path):
    db_path = tmp_path / "data" / "quantpublisher.sqlite3"

    returned_path = init_db(db_path)

    assert returned_path == db_path
    assert db_path.is_file()
    assert db_path.parent.is_dir()


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "quantpublisher.sqlite3"

    init_db(db_path)
    init_db(db_path)  # should not raise

    assert db_path.is_file()
