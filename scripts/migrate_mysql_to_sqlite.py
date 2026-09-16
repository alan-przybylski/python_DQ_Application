"""Copy the existing seven tables without changing or deleting anything in MySQL.

Usage: python -m scripts.migrate_mysql_to_sqlite --config config/sqlconfig.ini
Requires the optional migration dependency group, not needed by the application.
"""

import argparse
import configparser
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import os
import uuid

from config.paths import DATABASE_PATH, DATA_DIR
from database.connection import get_connection, initialize_database


TABLES = ("customers", "users", "data_load_log", "dq_rules", "dq_rules_history", "dq_results", "dq_field_results")
KPI_SQL = """
    SELECT rule_id, id, DATE(timestamp),
           ROUND(100.0 * SUM(passed_count) / NULLIF(SUM(passed_count) + SUM(failed_count), 0), 2)
    FROM dq_results GROUP BY rule_id, DATE(timestamp), id ORDER BY rule_id, DATE(timestamp), id
"""


def serializable(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def canonical_rows(rows):
    return sorted(json.dumps(list(row), ensure_ascii=False, sort_keys=True) for row in rows)


def read_mysql_snapshot(config_path):
    import mysql.connector

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    settings = {key: parser.get("mysql", key) for key in ("host", "user", "password", "database")}
    connection = mysql.connector.connect(**settings, connection_timeout=10)
    cursor = connection.cursor()
    try:
        connection.start_transaction(consistent_snapshot=True, readonly=True)
        cursor.execute("SHOW FULL TABLES")
        found = cursor.fetchall()
        if {name for name, kind in found} != set(TABLES) or any(kind != "BASE TABLE" for name, kind in found):
            raise ValueError("Source schema differs from the verified seven tables; migration stopped without copying a partial database.")
        cursor.execute("SELECT VERSION(), @@session.time_zone, @@system_time_zone, NOW(), UTC_TIMESTAMP()")
        server = [serializable(value) for value in cursor.fetchone()]
        snapshot = {"format": 1, "created_at": datetime.now().isoformat(), "server": server, "tables": {}, "active_rules": []}
        for table in TABLES:
            cursor.execute(f"SHOW CREATE TABLE `{table}`")
            ddl = cursor.fetchone()[1]
            cursor.execute(f"SELECT * FROM `{table}`")
            columns = [column[0] for column in cursor.description]
            rows = [[serializable(value) for value in row] for row in cursor.fetchall()]
            cursor.execute("SELECT AUTO_INCREMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (settings["database"], table))
            snapshot["tables"][table] = {"columns": columns, "rows": rows, "ddl": ddl, "next_id": cursor.fetchone()[0]}

        cursor.execute("SELECT id, sql_query FROM dq_rules WHERE status='ACTIVE' ORDER BY id")
        rules = cursor.fetchall()
        for rule_id, query in rules:
            if not query.lstrip().lower().startswith("select "):
                raise ValueError(f"Active rule {rule_id} is not a SELECT; comparison stopped.")
            cursor.execute(query)
            columns = [column[0] for column in cursor.description]
            rows = [[serializable(value) for value in row] for row in cursor.fetchall()]
            snapshot["active_rules"].append({"id": rule_id, "sql": query, "columns": columns, "rows": rows})
        cursor.execute(KPI_SQL)
        snapshot["kpi"] = [[serializable(value) for value in row] for row in cursor.fetchall()]
        return snapshot
    finally:
        cursor.close()
        connection.rollback()
        connection.close()


def verify_snapshot(connection, snapshot):
    report = {"tables": {}, "active_rules": {}, "kpi_rows": 0}
    for table in TABLES:
        content = snapshot["tables"][table]
        columns = content["columns"]
        expected = [list(row) for row in content["rows"]]
        # SQLite stores full rule versions as text; old MySQL integer values are preserved as text.
        if table == "dq_results":
            version_index = columns.index("rule_version")
            for row in expected:
                row[version_index] = str(row[version_index])
        quoted = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
        actual = connection.execute(f'SELECT {quoted} FROM "{table}"').fetchall()
        if canonical_rows(expected) != canonical_rows(actual):
            raise ValueError(f"Data mismatch in {table}; refusing to activate the new database.")
        digest = hashlib.sha256("\n".join(canonical_rows(actual)).encode("utf-8")).hexdigest()
        report["tables"][table] = {"rows": len(actual), "sha256": digest}

    connection.execute("PRAGMA query_only = ON")
    try:
        for rule in snapshot["active_rules"]:
            cursor = connection.execute(rule["sql"])
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            if columns != rule["columns"] or canonical_rows(rows) != canonical_rows(rule["rows"]):
                raise ValueError(f"Rule {rule['id']} differs between MySQL and SQLite; migration stopped.")
            report["active_rules"][str(rule["id"])] = {"rows": len(rows), "identical": True}
        actual_kpi = connection.execute(KPI_SQL).fetchall()
        if canonical_rows(actual_kpi) != canonical_rows(snapshot["kpi"]):
            raise ValueError("Historical KPI values differ; migration stopped.")
        report["kpi_rows"] = len(actual_kpi)
    finally:
        connection.execute("PRAGMA query_only = OFF")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Foreign key verification failed.")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity verification failed.")
    return report


def migrate_snapshot(snapshot, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Destination already exists and will not be overwritten: {destination}")
    if set(snapshot["tables"]) != set(TABLES):
        raise ValueError("Snapshot must contain exactly the seven existing application tables.")
    staging = destination.with_name(destination.name + ".migration-" + uuid.uuid4().hex)
    initialize_database(staging)
    connection = get_connection(staging)
    try:
        with connection:
            for table in TABLES:
                content = snapshot["tables"][table]
                expected_columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
                if content["columns"] != expected_columns:
                    raise ValueError(f"Unexpected columns in {table}; no data was discarded.")
                quoted = ", ".join('"' + column.replace('"', '""') + '"' for column in content["columns"])
                placeholders = ",".join("?" for _ in content["columns"])
                connection.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', content["rows"])
                next_id = content.get("next_id")
                if next_id:
                    connection.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))
                    connection.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, int(next_id) - 1))
            report = verify_snapshot(connection, snapshot)
    except Exception:
        connection.close()
        # Only this command's uniquely named staging file is removed; the source snapshot remains.
        staging.unlink(missing_ok=True)
        raise
    else:
        connection.close()
    # Publishing with a hard link refuses to overwrite even if another process creates the target.
    os.link(staging, destination)
    staging.unlink()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/sqlconfig.ini"))
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--snapshot", type=Path, help="Use an existing local JSON snapshot instead of connecting to MySQL.")
    args = parser.parse_args()
    if args.database.exists():
        raise SystemExit("Destination database already exists. It has not been overwritten.")
    migration_dir = DATA_DIR / "migration"
    migration_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        snapshot_path = args.snapshot.resolve()
    else:
        snapshot = read_mysql_snapshot(args.config)
        snapshot_path = migration_dir / f"mysql_snapshot_{stamp}.json"
        with snapshot_path.open("x", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
    report = migrate_snapshot(snapshot, args.database)
    report["snapshot"] = str(snapshot_path)
    report["database"] = str(args.database.resolve())
    report_path = migration_dir / f"verification_{stamp}.json"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
