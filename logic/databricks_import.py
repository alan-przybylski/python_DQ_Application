"""Read-only Databricks downloads; explicit, atomic local SQLite snapshots."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math
import re
from urllib.parse import quote as url_quote

from config.i18n import AppError
from database.connection import get_connection
from logic.datasets import create_table, table_columns, checked_table, quote
from logic.table_editor import backup_locked_database

MAX_ROWS = 100_000
MAX_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Source:
    hostname: str
    http_path: str
    catalog: str
    schema: str
    table: str

    def validate(self):
        host = self.hostname.lower()
        if not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host
        ) or not host.endswith((".databricks.com", ".azuredatabricks.net")):
            raise AppError(
                "Enter a Databricks server hostname without https:// or a port."
            )
        if not re.fullmatch(
            r"/sql/1\.0/(?:warehouses|endpoints)/[A-Za-z0-9_-]+", self.http_path
        ):
            raise AppError("Enter the SQL warehouse HTTP path from Connection details.")
        for part in (self.catalog, self.schema, self.table):
            if not part or any(ord(char) < 32 for char in part):
                raise AppError("Catalog, schema and table are required.")

    @property
    def sql_name(self):
        return ".".join(
            "`" + part.replace("`", "``") + "`"
            for part in (self.catalog, self.schema, self.table)
        )

    @property
    def reference(self):
        return (
            "databricks://"
            + self.hostname.lower()
            + "/"
            + "/".join(
                url_quote(part, safe="")
                for part in (self.catalog, self.schema, self.table)
            )
        )


@dataclass
class Snapshot:
    source: Source
    columns: list
    rows: list


def local_columns(description):
    columns, used = [], {"id"}
    kinds = {
        "tinyint": "INTEGER",
        "smallint": "INTEGER",
        "int": "INTEGER",
        "integer": "INTEGER",
        "bigint": "INTEGER",
        "boolean": "INTEGER",
        "float": "REAL",
        "double": "REAL",
        "real": "REAL",
        "string": "TEXT",
        "varchar": "TEXT",
        "char": "TEXT",
        "decimal": "TEXT",
        "date": "TEXT",
        "timestamp": "TEXT",
        "timestamp_ntz": "TEXT",
        "null": "TEXT",
        "void": "TEXT",
    }
    for field in description:
        original, source_type = str(field[0]), str(field[1]).lower()
        base_type = source_type.split("(")[0]
        if base_type not in kinds:
            raise AppError(
                "Unsupported source type for {column}: {kind}. No data was saved.",
                column=original,
                kind=source_type,
            )
        base = re.sub(r"[^A-Za-z0-9_]", "_", original)
        if not base or base[0].isdigit():
            base = "col_" + base
        if base.casefold() == "id":
            base = "source_id"
        name, suffix = base, 2
        while name.casefold() in used:
            name, suffix = f"{base}_{suffix}", suffix + 1
        used.add(name.casefold())
        columns.append(
            {
                "name": name,
                "type": kinds[base_type],
                "required": False,
                "source": original,
                "source_type": source_type,
            }
        )
    if not columns:
        raise AppError("The source has no columns.")
    return columns


def local_value(value, column):
    if value is None:
        return None
    kind = column["type"]
    if (
        kind == "INTEGER"
        and isinstance(value, (int, bool))
        and -(2**63) <= value < 2**63
    ):
        return int(value)
    if kind == "REAL" and isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if kind == "TEXT":
        if isinstance(value, str):
            return value
        if isinstance(value, Decimal) and value.is_finite():
            return str(value)  # Exact decimal, never silently rounded to float.
        if isinstance(value, (datetime, date)):
            return value.isoformat()
    raise AppError(
        "Unsupported value in column {column}. No data was saved.",
        column=column["source"],
    )


def connect_source(source):
    from databricks import sql

    return sql.connect(
        server_hostname=source.hostname,
        http_path=source.http_path,
        auth_type="databricks-oauth",
        user_agent_entry="DQ-Studio",
        _socket_timeout=30,
        _retry_stop_after_attempts_count=2,
    )


def download(source, row_limit=10_000, cancel=None, connect=None):
    source.validate()
    if not isinstance(row_limit, int) or not 1 <= row_limit <= MAX_ROWS:
        raise AppError("The row limit must be between 1 and 100000.")

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise AppError("Download cancelled. No local data was changed.")

    check_cancel()
    try:
        with (connect or connect_source)(source) as connection:
            check_cancel()
            with connection.cursor() as cursor:
                # A read-only, single SELECT; identifiers are separately quoted.
                # Fetch one extra row to detect overflow, never import a silent sample.
                cursor.execute(f"SELECT * FROM {source.sql_name} LIMIT {row_limit + 1}")
                columns = local_columns(cursor.description)
                rows, size = [], 0
                while True:
                    check_cancel()
                    batch = cursor.fetchmany(500)
                    if not batch:
                        break
                    for row in batch:
                        if len(row) != len(columns):
                            raise AppError(
                                "Source schema changed. Download the table again."
                            )
                        values = tuple(
                            local_value(value, column)
                            for value, column in zip(row, columns)
                        )
                        # Include approximate Python container/value overhead, not only
                        # text payload (a wide all-NULL source still consumes memory).
                        size += 64 + sum(
                            64 + len(str(value).encode("utf-8")) for value in values
                        )
                        if size > MAX_BYTES:
                            raise AppError(
                                "The snapshot exceeds 50 MB. Use a smaller source view."
                            )
                        rows.append(values)
                        if len(rows) > row_limit:
                            raise AppError(
                                "Source exceeds the row limit. Increase the limit or use a smaller view; nothing was imported."
                            )
                check_cancel()
                return Snapshot(source, columns, rows)
    except AppError:
        raise
    except Exception:
        # Do not expose authentication headers, endpoint diagnostics or row values.
        check_cancel()
        raise AppError(
            "Databricks download failed. Check connection details, browser sign-in, warehouse availability and SELECT permissions."
        ) from None


def save_snapshot(snapshot, table, username, replace=False):
    """Refresh only an earlier snapshot of the same source and identical schema."""
    connection = get_connection()
    backup = None
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if replace:
                checked_table(connection, table)
                source = connection.execute(
                    "SELECT file_name FROM data_load_log WHERE table_name=? ORDER BY id DESC LIMIT 1",
                    (table,),
                ).fetchone()
                if not source or source[0] != snapshot.source.reference:
                    raise AppError(
                        "Refresh requires a previous Databricks import from this exact source. Choose a new local table."
                    )
                columns = table_columns(table, connection)
                expected = [("id", "INTEGER", True, False)] + [
                    (c["name"], c["type"], False, False) for c in snapshot.columns
                ]
                actual = [
                    (c["name"], c["type"], c["pk"], c["required"]) for c in columns
                ]
                if actual != expected:
                    raise AppError(
                        "Local and source columns differ. Import into a new table; the existing table was not changed."
                    )
                # Reject external triggers/FKs/indexes rather than firing hidden side effects.
                from logic.table_editor import simple_definitions

                simple_definitions(connection, table)
                backup = backup_locked_database(connection, "before_databricks_refresh")
                connection.execute(f"DELETE FROM {quote(table)}")
            else:
                create_table(connection, table, snapshot.columns)
            names = [c["name"] for c in snapshot.columns]
            # Local IDs describe this snapshot; explicit numbering does not imply
            # that the source has a unique key or stable ordering across refreshes.
            statement = f"INSERT INTO {quote(table)} ({', '.join(map(quote, ['id', *names]))}) VALUES ({', '.join('?' for _ in range(len(names) + 1))})"
            connection.executemany(
                statement, ((i, *row) for i, row in enumerate(snapshot.rows, 1))
            )
            connection.execute(
                "INSERT INTO data_load_log(table_name,file_name,row_count,loaded_by) VALUES(?,?,?,?)",
                (table, snapshot.source.reference, len(snapshot.rows), username),
            )
        return len(snapshot.rows), backup
    finally:
        connection.close()
