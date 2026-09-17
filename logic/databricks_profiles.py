"""Atomic, non-secret connection preferences, separate for each local workspace."""

import json
import os
from pathlib import Path
import tempfile

from config.db_config import config
from config.i18n import AppError
from logic.databricks_import import Source

FIELDS = frozenset({"hostname", "http_path", "catalog", "schema", "table"})


def profile_path():
    return Path(config["database"]).with_suffix(".databricks-profiles.json")


def checked_settings(settings):
    if not isinstance(settings, dict) or set(settings) != FIELDS:
        raise AppError(
            "Profiles accept connection settings only, never passwords or tokens."
        )
    if any(
        not isinstance(value, str) or len(value) > 1000 for value in settings.values()
    ):
        raise AppError("Invalid profile settings.")
    clean = {key: value.strip() for key, value in settings.items()}
    Source(**{**clean, "table": clean["table"] or "_optional_table"}).validate()
    return clean


def load_profiles():
    path = profile_path()
    if not path.exists():
        return {"version": 1, "selected": "", "profiles": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if set(value) != {"version", "selected", "profiles"} or value["version"] != 1:
            raise ValueError
        profiles = value["profiles"]
        if not isinstance(profiles, dict) or not isinstance(value["selected"], str):
            raise ValueError
        if value["selected"] and value["selected"] not in profiles:
            raise ValueError
        names = set()
        for name, settings in profiles.items():
            if not name.strip() or len(name) > 80 or name.casefold() in names:
                raise ValueError
            names.add(name.casefold())
            checked_settings(settings)
        return value
    except (OSError, ValueError, TypeError, AttributeError):
        raise AppError(
            "Cannot read the profiles file. It was not overwritten. Check: {path}",
            path=path,
        ) from None


def _write(value):
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def save_profile(name, settings, overwrite=False):
    name = name.strip()
    if not name or len(name) > 80:
        raise AppError("Enter a profile name (1–80 characters).")
    settings = checked_settings(settings)
    value = load_profiles()
    existing = next(
        (n for n in value["profiles"] if n.casefold() == name.casefold()), None
    )
    if existing is not None and not overwrite:
        raise AppError("Profile already exists. Confirm replacement first.")
    if existing is not None:
        del value["profiles"][existing]
    value["profiles"][name] = settings
    value["selected"] = name
    _write(value)


def select_profile(name):
    value = load_profiles()
    if name not in value["profiles"]:
        raise AppError("Select a saved profile.")
    value["selected"] = name
    _write(value)
    return dict(value["profiles"][name])


def delete_profile(name):
    value = load_profiles()
    if name not in value["profiles"]:
        raise AppError("Select a saved profile.")
    del value["profiles"][name]
    if value["selected"] == name:
        value["selected"] = ""
    _write(value)
