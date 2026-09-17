"""Conservative dataset-only schema editing with lossless conversion and backups."""

from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from config.i18n import AppError
from database.connection import get_connection
from logic.datasets import checked_table, identifier, quote, table_columns, TYPES


def backup_locked_database(connection, reason):
    """Caller holds BEGIN IMMEDIATE; another reader backs up the pre-write state."""
    filename = connection.execute("PRAGMA database_list").fetchone()[2]
    directory = Path(filename).parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix=reason + "_", dir=directory)) / "app.db"
    reader = get_connection(filename)
    backup = get_connection(destination)
    try:
        reader.backup(backup)
    finally:
        reader.close()
        backup.close()
    return destination


def strict_conversion(value, kind):
    """No truncation, lost leading zeros, rounding or NULL/empty conflation."""
    if value is None:
        return None
    if kind == "TEXT":
        if isinstance(value, bytes):
            raise AppError("Binary values cannot be converted automatically.")
        return str(value)
    try:
        if isinstance(value, (bytes, bool)):
            raise ValueError
        if isinstance(value, str):
            if value != value.strip() or not value or re.match(r"[+-]?0\d", value):
                raise ValueError
        decimal = Decimal(str(value))
        if not decimal.is_finite():
            raise ValueError
        if kind == "INTEGER":
            number = int(decimal)
            if decimal != number or not -(2**63) <= number < 2**63:
                raise ValueError
            return number
        if kind == "REAL":
            number = float(value)
            if not math.isfinite(number) or Decimal(str(number)) != decimal:
                raise ValueError
            # Large integers must remain exactly representable, not merely print alike.
            if (
                decimal == decimal.to_integral_value()
                and Decimal.from_float(number) != decimal
            ):
                raise ValueError
            return number
    except ValueError, TypeError, OverflowError, InvalidOperation:
        pass
    raise AppError("Conversion would lose data. No changes were saved.")


def protect_rules(connection, table, column):
    """SQLite resolves aliases, joins and quoted names; no SQL execution occurs.

    Protect current ACTIVE and INACTIVE definitions. Historical versions remain
    immutable snapshots, not runnable rules. Unparseable current SQL fails closed.
    """
    rules = connection.execute("SELECT id,sql_query FROM dq_rules").fetchall()
    for rule_id, sql in rules:
        references = set()

        def authorize(action, first, second, database, trigger):
            if action == sqlite3.SQLITE_READ:
                references.add(((first or "").casefold(), (second or "").casefold()))
            if action in (
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
                sqlite3.SQLITE_RECURSIVE,
            ):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        try:
            connection.execute("EXPLAIN " + sql).fetchall()
        except sqlite3.Error, TypeError:
            raise AppError(
                "Cannot verify rule #{rule}. Fix its SQL before editing columns.",
                rule=rule_id,
            ) from None
        finally:
            connection.set_authorizer(None)
        if (table.casefold(), column.casefold()) in references or (
            table.casefold(),
            "",
        ) in references:
            raise AppError(
                "Column is used by rule #{rule}. Update the rule before editing this column.",
                rule=rule_id,
            )


def simple_definitions(connection, table):
    """Rebuild only our plain dataset schemas; never drop unknown constraints.

    Original SQL declarations (including collations) are retained verbatim.
    External views, triggers, indexes and foreign keys require a manual migration.
    """
    sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]
    body = re.fullmatch(r"CREATE\s+TABLE\s+.+?\((.*)\)\s*", sql, re.I | re.S)
    if not body:
        raise AppError(
            "This table has advanced SQL dependencies. Use a reviewed migration."
        )
    definitions = [part.strip() for part in body[1].split(",")]
    columns = table_columns(table, connection)
    if len(definitions) != len(columns):
        raise AppError(
            "This table has advanced SQL dependencies. Use a reviewed migration."
        )
    for definition, column in zip(definitions, columns):
        name = re.escape(column["name"])
        pattern = rf'(?:"{name}"|{name})\s+(?:TEXT|INTEGER|REAL)(?:\s+COLLATE\s+(?:MYSQL_AI_CI|BINARY|NOCASE|RTRIM))?(?:\s+PRIMARY\s+KEY)?(?:\s+AUTOINCREMENT)?(?:\s+NOT\s+NULL)?'
        if not re.fullmatch(pattern, definition, re.I):
            raise AppError(
                "This table has advanced SQL dependencies. Use a reviewed migration."
            )
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') OR (type='index' AND tbl_name=? AND sql IS NOT NULL)",
        (table,),
    ).fetchone():
        raise AppError(
            "This table has advanced SQL dependencies. Use a reviewed migration."
        )
    for (name,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ):
        for foreign_key in connection.execute(
            f"PRAGMA foreign_key_list({quote(name)})"
        ):
            if name == table or foreign_key[2].casefold() == table.casefold():
                raise AppError(
                    "This table has advanced SQL dependencies. Use a reviewed migration."
                )
    return definitions


def edit_column(table, action, column=None, name=None, kind="TEXT", required=False):
    """Apply one confirmed edit atomically; return the recoverable backup path."""
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            checked_table(connection, table)
            columns = table_columns(table, connection)
            if action not in {"add", "modify", "drop"} or kind not in TYPES:
                raise AppError("Supported types: TEXT, INTEGER, REAL.")
            current = next((item for item in columns if item["name"] == column), None)
            if action != "add" and current is None:
                raise AppError("Select a column.")
            if action != "add" and (current["pk"] or column.casefold() == "id"):
                raise AppError("The technical id column cannot be edited.")
            if action != "drop":
                identifier(name or "")
                if name.casefold() == "id" or any(
                    item["name"].casefold() == name.casefold() and item is not current
                    for item in columns
                ):
                    raise AppError("Column names must be unique; id is reserved.")
            # Fail closed for unmanaged schema dependencies, even on rename/drop.
            definitions = simple_definitions(connection, table)
            if action != "add":
                protect_rules(connection, table, column)
            else:
                # SELECT * rules could change their output contract after adding a column.
                # Explicit-column rules are unaffected; validate wildcard readers conservatively.
                for rid, query in connection.execute(
                    "SELECT id,sql_query FROM dq_rules"
                ):
                    if "*" in (query or ""):
                        try:
                            protect_rules_for_add(connection, table, rid, query)
                        except sqlite3.Error:
                            raise AppError(
                                "Cannot verify rule #{rule}. Fix its SQL before editing columns.",
                                rule=rid,
                            ) from None
            backup = backup_locked_database(connection, "before_column_edit")
            if action == "add":
                connection.execute(
                    f"ALTER TABLE {quote(table)} ADD COLUMN {quote(name)} {kind}"
                    + (" NOT NULL" if required else "")
                )
            elif action == "drop":
                connection.execute(
                    f"ALTER TABLE {quote(table)} DROP COLUMN {quote(column)}"
                )
            elif current["type"] == kind and current["required"] == required:
                if name != column:
                    connection.execute(
                        f"ALTER TABLE {quote(table)} RENAME COLUMN {quote(column)} TO {quote(name)}"
                    )
            else:
                index = next(i for i, item in enumerate(columns) if item is current)
                collation = re.search(r"\s+COLLATE\s+\w+", definitions[index], re.I)
                definitions[index] = (
                    f"{quote(name)} {kind}"
                    + (collation[0] if collation else "")
                    + (" NOT NULL" if required else "")
                )
                temporary = "dq_edit_" + uuid.uuid4().hex
                sequence = connection.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name=?", (table,)
                ).fetchone()
                connection.execute(
                    f"CREATE TABLE {quote(temporary)} ({', '.join(definitions)})"
                )
                insert = f"INSERT INTO {quote(temporary)} VALUES ({', '.join('?' for _ in columns)})"
                reader = connection.execute(f"SELECT * FROM {quote(table)}")
                while rows := reader.fetchmany(500):
                    converted = []
                    for row in rows:
                        row = list(row)
                        row[index] = strict_conversion(row[index], kind)
                        if required and row[index] is None:
                            raise AppError("A value is required.")
                        converted.append(row)
                    connection.executemany(insert, converted)
                connection.execute(f"DROP TABLE {quote(table)}")
                connection.execute(
                    f"ALTER TABLE {quote(temporary)} RENAME TO {quote(table)}"
                )
                if sequence:
                    updated = connection.execute(
                        "UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?",
                        (sequence[0], table),
                    )
                    if not updated.rowcount:
                        connection.execute(
                            "INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)",
                            (table, sequence[0]),
                        )
                if connection.execute("PRAGMA foreign_key_check").fetchone():
                    raise AppError(
                        "This table has advanced SQL dependencies. Use a reviewed migration."
                    )
            return backup
    finally:
        connection.close()


def protect_rules_for_add(connection, table, rule_id, query):
    references = set()

    def authorize(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_READ:
            references.add((first or "").casefold())
        return (
            sqlite3.SQLITE_OK
            if action
            in (
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
                sqlite3.SQLITE_RECURSIVE,
            )
            else sqlite3.SQLITE_DENY
        )

    connection.set_authorizer(authorize)
    try:
        connection.execute("EXPLAIN " + query).fetchall()
    finally:
        connection.set_authorizer(None)
    if table.casefold() in references:
        raise AppError(
            "Rule #{rule} uses a wildcard or expression. Review it before adding columns.",
            rule=rule_id,
        )
