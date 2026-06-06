import pytest
from app.repositories.database import Database
from app.repositories.settings import SettingsRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    return SettingsRepository(db)


def test_set_and_get(repo):
    repo.set("history_enabled", "true")
    assert repo.get("history_enabled") == "true"


def test_get_missing_returns_none(repo):
    assert repo.get("nonexistent") is None


def test_set_overwrites(repo):
    repo.set("k", "v1")
    repo.set("k", "v2")
    assert repo.get("k") == "v2"


def test_get_bool(repo):
    repo.set("a", "true")
    repo.set("b", "false")
    repo.set("c", "1")
    assert repo.get_bool("a") is True
    assert repo.get_bool("b") is False
    assert repo.get_bool("c") is True
    assert repo.get_bool("missing", default=True) is True


def test_all_keys(repo):
    repo.set("a", "1")
    repo.set("b", "2")
    keys = repo.all_keys()
    assert set(keys) == {"a", "b"}
