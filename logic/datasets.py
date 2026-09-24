"""Dataset metadata, lossless CSV reading, atomic imports and explicit exports."""

import csv
from dataclasses import dataclass
import io
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from config.i18n import AppError, tr
from database.connection import get_connection
from logic.dataset_types import TYPES, INTEGER_BITS, supported, storage_type, logical_type, typed_value, decimal_spec

INTERNAL_TABLES = frozenset(
    {
        "users",
        "data_load_log",
        "dq_rules",
        "dq_rules_history",
        "dq_results",
        "dq_field_results",
        "dq_runs",
        "dq_tickets",
        "dq_ticket_events",
        "dq_remote_links",
        "dq_remote_versions",
        "dq_remote_receipts",
        "dq_references",
    }
)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def identifier(name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise AppError(
            "Identifiers must start with a letter or underscore and contain only letters, digits and underscores."
        )
    return name


def list_tables(connection=None):
    own = connection is None
    connection = connection or get_connection()
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if row[0].casefold() not in INTERNAL_TABLES
            and not row[0].casefold().startswith("sqlite_")
        ]
    finally:
        if own:
            connection.close()


def checked_table(connection, name):
    names = list_tables(connection)
    if name not in names:
        raise AppError("Table does not exist.")
    return quote(name)


def table_columns(table, connection=None):
    own = connection is None
    connection = connection or get_connection()
    try:
        checked_table(connection, table)
        return [
            {
                "name": row[1],
                "type": logical_type(row[2]),
                "required": bool(row[3])
                or bool(row[5] and row[2].upper() != "INTEGER"),
                "default": row[4],
                "pk": bool(row[5]),
            }
            for row in connection.execute(f"PRAGMA table_info({quote(table)})")
        ]
    finally:
        if own:
            connection.close()


@dataclass
class CsvData:
    headers: list
    rows: list
    filename: str


def read_csv(path):
    content = Path(path).read_bytes()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1250")
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
        reader = csv.reader(io.StringIO(text, newline=""), dialect)
    except csv.Error:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=";")
    headers = next(reader, None)
    if not headers:
        raise AppError("CSV has no header.")
    headers = [name.strip() for name in headers]
    if any(not name for name in headers) or len(
        {name.casefold() for name in headers}
    ) != len(headers):
        raise AppError("CSV headers must be nonempty and unique.")
    rows = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(headers):
            raise AppError(
                "CSV row {row} has a different number of fields.", row=reader.line_num
            )
        rows.append(row)
    return CsvData(headers, rows, Path(path).name)


def suggested_type(values):
    values = [value.strip() for value in values if value.strip()]
    if not values:
        return "TEXT"
    # Leading zeros are identifiers, not quantities.
    if any(re.match(r"[+-]?0\d", value) for value in values):
        return "TEXT"
    if all(re.fullmatch(r"[+-]?\d+", value) for value in values):
        return "INTEGER"
    try:
        if all(math.isfinite(float(value)) for value in values):
            return "REAL"
    except ValueError:
        pass
    return "TEXT"


def validate_definition(table, columns):
    identifier(table)
    if table.casefold() in INTERNAL_TABLES or table.casefold().startswith(
        ("sqlite_", "dq_")
    ):
        raise AppError("This table name is reserved.")
    if not columns:
        raise AppError("At least one column is required.")
    if len({column["name"].casefold() for column in columns}) != len(columns):
        raise AppError("Column names must be unique.")
    for column in columns:
        identifier(column["name"])
        if not supported(column["type"]):
            raise AppError("Unsupported dataset type: {kind}", kind=column['type'])
        if column["name"].casefold() == "id" and (
            column["name"] != "id" or column["type"] not in ('INTEGER','TEXT')
        ):
            raise AppError("The id column must be INTEGER or TEXT.")


def create_table(connection, table, columns):
    validate_definition(table, columns)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? COLLATE NOCASE", (table,)
    ).fetchone():
        raise AppError("Table already exists.")
    definitions = []
    if not any(column["name"] == "id" for column in columns):
        definitions.append('"id" INTEGER PRIMARY KEY AUTOINCREMENT')
    for column in columns:
        definition = f"{quote(column['name'])} {storage_type(column['type'])}"
        if column["name"] == "id":
            definition += " PRIMARY KEY" + (
                " AUTOINCREMENT" if column["type"] == "INTEGER" else " NOT NULL"
            )
        elif column.get("required"):
            definition += " NOT NULL"
        definitions.append(definition)
    connection.execute(f"CREATE TABLE {quote(table)} ({', '.join(definitions)})")


def create_dataset(table, columns):
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            create_table(connection, table, columns)
    finally:
        connection.close()


def converted(value, column):
    if value == "":
        if column["required"] and column.get("default") is None:
            raise AppError("A value is required.")
        return None
    kind = column["type"]
    if kind in INTEGER_BITS:
        if not re.fullmatch(r"[+-]?\d+", value.strip()):
            raise AppError("Expected an integer.")
        number = int(value)
        bits = INTEGER_BITS[kind]
        if not -(2**(bits-1)) <= number < 2**(bits-1):
            raise AppError("Expected an integer.")
        return number
    if kind in {"REAL", "FLOAT", "DOUBLE"}:
        try:
            number = float(value)
            if math.isfinite(number):
                return number
        except ValueError:
            pass
        raise AppError("Expected a finite number using a decimal point.")
    if kind in ('DATE','TIMESTAMP','TIMESTAMP_NTZ','BOOLEAN') or decimal_spec(kind):
        return typed_value(value, kind)
    return value


def import_data(data, table, username, mapping=None, new_columns=None):
    if not data.rows:
        raise AppError("CSV has no data rows.")
    mapping = mapping if mapping is not None else dict(zip(data.headers, data.headers))
    if set(mapping) != set(data.headers) or any(
        value == "" for value in mapping.values()
    ):
        raise AppError("Map every CSV column or explicitly ignore it.")
    targets = [mapping[source] for source in data.headers if mapping[source]]
    if not targets:
        raise AppError("No columns selected for import.")
    if len(set(targets)) != len(targets):
        raise AppError("Multiple source columns map to the same target.")
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if new_columns is not None:
                create_table(connection, table, new_columns)
            columns = {
                column["name"]: column for column in table_columns(table, connection)
            }
            for name in targets:
                if name not in columns:
                    raise AppError("Unknown column: {column}", column=name)
            for name, column in columns.items():
                if (
                    column["required"]
                    and column["default"] is None
                    and name not in targets
                ):
                    raise AppError("Missing required column: {column}", column=name)
            converted_rows, errors, seen_ids = [], [], set()
            selected = [
                (index, columns[mapping[source]])
                for index, source in enumerate(data.headers)
                if mapping[source]
            ]
            for row_number, row in enumerate(data.rows, 2):
                values = []
                for index, column in selected:
                    try:
                        values.append(converted(row[index], column))
                    except AppError as error:
                        errors.append(
                            tr(
                                "Row {row}, {column}: {detail}",
                                row=row_number,
                                column=column["name"],
                                detail=str(error),
                            )
                        )
                if len(values) == len(targets) and "id" in targets:
                    value = values[targets.index("id")]
                    if value is not None:
                        if value in seen_ids:
                            errors.append(
                                tr(
                                    "Row {row}, {column}: {detail}",
                                    row=row_number,
                                    column="id",
                                    detail=tr("Duplicate id in the CSV."),
                                )
                            )
                        seen_ids.add(value)
                converted_rows.append(values)
            if errors:
                raise AppError(
                    "Import rejected. No data was saved.\n{details}",
                    details="\n".join(errors[:30]),
                )
            insert = f"INSERT INTO {quote(table)} ({', '.join(map(quote, targets))}) VALUES ({', '.join('?' for _ in targets)})"
            if "id" in targets and columns["id"]["pk"]:
                update = [
                    f"{quote(name)}=excluded.{quote(name)}"
                    for name in targets
                    if name != "id"
                ]
                insert += ' ON CONFLICT("id") DO ' + (
                    "UPDATE SET " + ", ".join(update) if update else "NOTHING"
                )
            connection.executemany(insert, converted_rows)
            connection.execute(
                "INSERT INTO data_load_log(table_name,file_name,row_count,loaded_by) VALUES(?,?,?,?)",
                (table, data.filename, len(data.rows), username),
            )
        return len(data.rows)
    except sqlite3.Error as error:
        raise AppError(
            "Import rejected. No data was saved.\n{details}", details=str(error)
        ) from error
    finally:
        connection.close()


def write_csv(path, headers, rows, spreadsheet_safe=True):
    path = Path(path)
    if path.suffix.casefold() != ".csv":
        raise AppError("Choose a .csv filename.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            suffix=".csv.tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream, delimiter=";")
            writer.writerow(headers)
            count = 0
            for row in rows:
                writer.writerow(
                    [
                        "'" + value
                        if spreadsheet_safe
                        and isinstance(value, str)
                        and value.lstrip().startswith(("=", "+", "-", "@"))
                        else value
                        for value in row
                    ]
                )
                count += 1
        os.replace(temporary, path)
        return count
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_table(table, path, spreadsheet_safe=True):
    connection = get_connection()
    try:
        cursor = connection.execute(f"SELECT * FROM {checked_table(connection, table)}")
        return write_csv(
            path, [column[0] for column in cursor.description], cursor, spreadsheet_safe
        )
    finally:
        connection.close()


def export_template(table, path):
    return write_csv(
        path, [column["name"] for column in table_columns(table)], [], False
    )
