"""SQLite connections and compatibility functions used by existing DQ rules."""

from pathlib import Path
import re
import sqlite3
import unicodedata

from config.db_config import config


def _comparison_key(value):
    return "".join(
        character for character in unicodedata.normalize("NFD", value.casefold())
        if unicodedata.category(character) != "Mn"
    )


def _mysql_ai_ci(left, right):
    left, right = _comparison_key(left), _comparison_key(right)
    return (left > right) - (left < right)


def _regexp_like(value, pattern, match_type=""):
    if value is None or pattern is None:
        return None
    flags = re.IGNORECASE
    for option in match_type or "":
        if option == "c":
            flags &= ~re.IGNORECASE
        elif option == "i":
            flags |= re.IGNORECASE
        elif option == "m":
            flags |= re.MULTILINE
        elif option == "n":
            flags |= re.DOTALL
        else:
            raise ValueError(f"Unsupported REGEXP_LIKE option: {option}")
    return int(re.search(pattern, str(value), flags) is not None)


def get_connection(database=None):
    """Open persistent storage; callers retain their existing transaction boundaries."""
    destination = database if database is not None else config["database"]
    connection = sqlite3.connect(destination, timeout=10)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.create_collation("MYSQL_AI_CI", _mysql_ai_ci)
    connection.create_function("REGEXP", 2, lambda pattern, value: _regexp_like(value, pattern), deterministic=True)
    connection.create_function("REGEXP_LIKE", 2, _regexp_like, deterministic=True)
    connection.create_function("REGEXP_LIKE", 3, _regexp_like, deterministic=True)
    return connection


def initialize_database(database=None):
    destination = Path(database if database is not None else config["database"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = get_connection(destination)
    try:
        connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        connection.commit()
        from database.migrations import upgrade
        upgrade(connection, destination)
        from database.failure_flags import upgrade_failure_flags

        upgrade_failure_flags(connection, destination)
        from database.tickets import upgrade_tickets

        upgrade_tickets(connection)
        from database.rule_files import upgrade_rule_files

        upgrade_rule_files(connection)
        from database.databricks_sync import upgrade_databricks_sync

        upgrade_databricks_sync(connection)
        from database.references import upgrade_references
        upgrade_references(connection)
        from database.plain_sql import upgrade_plain_sql
        upgrade_plain_sql(connection)
        from database.workspaces import upgrade_workspaces
        upgrade_workspaces(connection, destination)
    finally:
        connection.close()


def dict_row_factory(cursor, row):
    return {column[0]: value for column, value in zip(cursor.description, row)}
