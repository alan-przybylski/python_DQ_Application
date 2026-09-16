import pytest

from config.db_config import config
from database.connection import initialize_database


@pytest.fixture
def sqlite_database(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    monkeypatch.setitem(config, "database", str(path))
    initialize_database(path)
    return path
