import json

import pytest

from config.db_config import config
from config.i18n import AppError
from logic import databricks_profiles as profiles


SETTINGS = dict(
    hostname="dbc-test.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/123",
    catalog="workspace",
    schema="default",
    table="customers",
)


def test_save_select_restart_update_delete(sqlite_database):
    profiles.save_profile("Test", SETTINGS)
    profiles.save_profile("Other", {**SETTINGS, "table": "orders"})
    assert profiles.load_profiles()["selected"] == "Other"
    assert profiles.select_profile("Test") == SETTINGS
    assert profiles.load_profiles()["selected"] == "Test"
    profiles.save_profile("Test", {**SETTINGS, "schema": "reporting"}, overwrite=True)
    assert profiles.select_profile("Test")["schema"] == "reporting"
    profiles.delete_profile("Test")
    assert list(profiles.load_profiles()["profiles"]) == ["Other"]
    assert profiles.load_profiles()["selected"] == ""


def test_duplicate_requires_confirmation(sqlite_database):
    profiles.save_profile("Test", SETTINGS)
    before = profiles.profile_path().read_bytes()
    with pytest.raises(AppError):
        profiles.save_profile("test", {**SETTINGS, "table": "orders"})
    assert profiles.profile_path().read_bytes() == before


@pytest.mark.parametrize("key", ["password", "access_token", "token", "secret"])
def test_no_secret_fields_can_be_saved(sqlite_database, key):
    with pytest.raises(AppError):
        profiles.save_profile("Test", {**SETTINGS, key: "sensitive"})
    assert not profiles.profile_path().exists()


def test_optional_table_and_database_isolation(sqlite_database, monkeypatch, tmp_path):
    profiles.save_profile("No table", {**SETTINGS, "table": ""})
    assert profiles.load_profiles()["profiles"]["No table"]["table"] == ""
    monkeypatch.setitem(config, "database", str(tmp_path / "demo.db"))
    assert profiles.load_profiles()["profiles"] == {}


def test_corrupt_file_is_not_overwritten(sqlite_database):
    profiles.profile_path().write_text("broken", encoding="utf-8")
    with pytest.raises(AppError):
        profiles.save_profile("Test", SETTINGS)
    assert profiles.profile_path().read_text() == "broken"


def test_atomic_failure_preserves_saved_profiles(sqlite_database, monkeypatch):
    profiles.save_profile("Test", SETTINGS)
    before = profiles.profile_path().read_bytes()

    def fail(*args):
        raise OSError("simulated interruption")

    monkeypatch.setattr(profiles.os, "replace", fail)
    with pytest.raises(OSError):
        profiles.save_profile("Other", SETTINGS)
    assert profiles.profile_path().read_bytes() == before
    assert not list(profiles.profile_path().parent.glob("*.tmp"))


def test_file_contains_only_expected_non_secret_fields(sqlite_database):
    profiles.save_profile("Test", SETTINGS)
    saved = json.loads(profiles.profile_path().read_text())
    assert saved == {"version": 1, "selected": "Test", "profiles": {"Test": SETTINGS}}
