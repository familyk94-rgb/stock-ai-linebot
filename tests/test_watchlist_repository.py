import sqlite3

from services.repositories.watchlist_repository import WatchlistRepository


def _insert(repository, *, user="user-1", stock="2330", name="台積電"):
    return repository.insert(
        line_user_id=user,
        stock_id=stock,
        stock_name=name,
        created_at="2026-07-17T10:00:00+08:00",
    )


def test_repository_creates_fixed_schema_and_persists_record(tmp_path):
    path = tmp_path / "nested" / "watchlist.db"
    repository = WatchlistRepository(path)

    assert _insert(repository) is True
    assert path.exists()
    assert repository.exists(line_user_id="user-1", stock_id="2330") is True
    assert repository.list_by_user(line_user_id="user-1") == [
        {
            "id": 1,
            "line_user_id": "user-1",
            "stock_id": "2330",
            "stock_name": "台積電",
            "created_at": "2026-07-17T10:00:00+08:00",
        }
    ]

    with sqlite3.connect(path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(watchlist_stocks)"
            ).fetchall()
        ]
    assert columns == ["id", "line_user_id", "stock_id", "stock_name", "created_at"]


def test_repository_duplicate_insert_is_ignored(tmp_path):
    repository = WatchlistRepository(tmp_path / "watchlist.db")
    assert _insert(repository) is True
    assert _insert(repository, name="不同名稱") is False
    assert len(repository.list_by_user(line_user_id="user-1")) == 1


def test_repository_delete_existing_and_missing_records(tmp_path):
    repository = WatchlistRepository(tmp_path / "watchlist.db")
    assert _insert(repository) is True
    assert repository.delete(line_user_id="user-1", stock_id="2330") is True
    assert repository.delete(line_user_id="user-1", stock_id="2330") is False
    assert repository.exists(line_user_id="user-1", stock_id="2330") is False


def test_repository_empty_list_and_user_isolation(tmp_path):
    repository = WatchlistRepository(tmp_path / "watchlist.db")
    assert repository.list_by_user(line_user_id="user-empty") == []
    assert _insert(repository, user="user-1") is True
    assert repository.list_by_user(line_user_id="user-2") == []


def test_repository_uses_configured_environment_path(monkeypatch, tmp_path):
    path = tmp_path / "configured" / "watchlist.db"
    monkeypatch.setenv("WATCHLIST_DB_PATH", str(path))
    repository = WatchlistRepository()
    assert repository.db_path == path
    assert _insert(repository)
