"""Read-only rule execution and durable, explicitly linked DQ runs."""

import json
import sqlite3
import time

from config.i18n import AppError
from database.connection import dict_row_factory, get_connection
from logic.datasets import checked_table, list_tables, write_csv


def evaluate(connection, sql, tables):
    from logic.references import resolve_local
    try:
        sql = resolve_local(connection,sql)
    except ValueError as error:
        raise AppError('Reference lookup failed: {detail}',detail=str(error)) from error
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }
    tables = {table.casefold() for table in tables}
    deadline = time.monotonic() + 10

    def authorize(action, first, second, database, source):
        if action not in allowed:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and first.casefold() not in tables:
            return sqlite3.SQLITE_DENY
        if (
            action == sqlite3.SQLITE_FUNCTION
            and (second or "").casefold() == "load_extension"
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    connection.set_authorizer(authorize)
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    try:
        cursor = connection.execute(sql)
        names = [column[0] for column in cursor.description or []]
        if (
            len(names) < 3
            or names[0] != "id"
            or names[1] in {"id", "dq_check"}
            or "dq_check" not in names
            or len(set(names)) != len(names)
        ):
            raise AppError(
                "Rule output must contain id, the tested field as the second column, and dq_check (0 = PASS, 1 = FAIL)."
            )
        records = [dict(zip(names, row)) for row in cursor.fetchall()]
        for record in records:
            if record["dq_check"] not in (0, 1):
                raise AppError(
                    "Rule output must contain id, the tested field as the second column, and dq_check (0 = PASS, 1 = FAIL)."
                )
            if record["id"] is None or str(record["id"]) == "":
                raise AppError("Rule record id cannot be empty.")
        return names[1], records
    finally:
        connection.set_progress_handler(None, 0)
        connection.set_authorizer(None)


def validate_rule(sql, table):
    from logic.sql_source import bind_source
    connection = get_connection()
    try:
        checked_table(connection, table)
        connection.execute("PRAGMA query_only=ON")
        evaluate(connection, bind_source(sql,table), list_tables(connection))
    except sqlite3.Error as error:
        raise AppError(
            "Rule SQL must be read-only and may access only dataset tables."
        ) from error
    finally:
        connection.close()


def error_text(message):
    # Previously created rules may store the message as a JSON string.
    try:
        decoded = json.loads(message or '""')
        if isinstance(decoded, str):
            return decoded
    except ValueError, TypeError:
        pass
    return message or "DQ check failed"


def run_checks(table, username, rule_id=None, include_remote=False):
    writer, reader = get_connection(), get_connection()
    try:
        writer.execute("BEGIN IMMEDIATE")
        checked_table(writer, table)
        if not writer.execute(
            "SELECT 1 FROM users WHERE username=? AND active=1", (username,)
        ).fetchone():
            raise AppError("Account is inactive.")
        rules = writer.execute(
            "SELECT id,version,description,error_message,sql_query,severity FROM dq_rules WHERE status='ACTIVE' AND target_table=?"
            + ("" if include_remote else " AND execution_mode='local'")
            + (" AND id=?" if rule_id is not None else "")
            + " ORDER BY id",
            (table, rule_id) if rule_id is not None else (table,),
        ).fetchall()
        cursor = writer.execute(
            "INSERT INTO dq_runs(table_name,username,mode,status,rules_requested) VALUES(?,?,?,'running',?)",
            (table, username, "single" if rule_id is not None else "all", len(rules)),
        )
        run_id = cursor.lastrowid
        reader.execute("PRAGMA query_only=ON")
        reader.execute("BEGIN")
        tables = list_tables(reader)
        errors, completed = [], 0
        for rid, version, description, message, sql, severity in rules:
            try:
                field, records = evaluate(reader, sql, tables)
            except (sqlite3.Error, AppError) as error:
                errors.append(
                    {
                        "rule_id": rid,
                        "description": description,
                        "version": version,
                        "message": str(error),
                    }
                )
                continue
            # A rule's KPI and detailed rows either both persist, or neither does.
            writer.execute("SAVEPOINT rule_result")
            try:
                passed = sum(record["dq_check"] == 0 for record in records)
                writer.execute(
                    "INSERT INTO dq_results(rule_id,rule_version,failed_count,passed_count,run_id) VALUES(?,?,?,?,?)",
                    (rid, version, len(records) - passed, passed, run_id),
                )
                writer.executemany(
                    """INSERT INTO dq_field_results
                    (rule_id,rule_version,record_id,field_name,field_value,test_result,error_message,target_table,run_id)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    [
                        (
                            rid,
                            version,
                            str(record["id"]),
                            field,
                            None if record[field] is None else str(record[field]),
                            record["dq_check"],
                            "" if record["dq_check"] == 0 else error_text(message),
                            table,
                            run_id,
                        )
                        for record in records
                    ],
                )
                from logic.tickets import sync_ticket

                sync_ticket(writer, rid, version, table, description, severity, run_id,
                            username, len(records) - passed, len(records))
                writer.execute("RELEASE rule_result")
                completed += 1
            except sqlite3.Error as error:
                writer.execute("ROLLBACK TO rule_result")
                writer.execute("RELEASE rule_result")
                errors.append(
                    {
                        "rule_id": rid,
                        "description": description,
                        "version": version,
                        "message": str(error),
                    }
                )
        reader.rollback()
        status = (
            "no_rules"
            if not rules
            else (
                "partial"
                if errors and completed
                else "failed"
                if errors
                else "completed"
            )
        )
        writer.execute(
            "UPDATE dq_runs SET completed_at=datetime('now','localtime'),status=?,rules_completed=?,execution_errors=? WHERE id=?",
            (status, completed, json.dumps(errors, ensure_ascii=False), run_id),
        )
        writer.commit()
        return run_id
    except Exception:
        writer.rollback()
        raise
    finally:
        reader.close()
        writer.close()


def runs_for_table(table):
    connection = get_connection()
    try:
        connection.row_factory = dict_row_factory
        return connection.execute(
            """SELECT r.*,
            (SELECT json_extract(v.payload,'$.description') FROM dq_remote_receipts x
             JOIN dq_remote_versions v ON v.revision=x.revision
             JOIN dq_remote_links l ON l.id=v.link_id AND l.endpoint=x.endpoint
             JOIN dq_rules q ON q.id=l.rule_id AND q.rule_key=x.rule_key
             WHERE x.local_run_id=r.id LIMIT 1) AS rule_description
            FROM dq_runs r WHERE r.table_name=? ORDER BY r.started_at DESC,r.id DESC""", (table,)
        ).fetchall()
    finally:
        connection.close()


def run_details(run_id):
    connection = get_connection()
    connection.row_factory = dict_row_factory
    try:
        run = connection.execute(
            "SELECT * FROM dq_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not run:
            return None
        totals = connection.execute(
            "SELECT COALESCE(SUM(passed_count),0) AS passed,COALESCE(SUM(failed_count),0) AS failed FROM dq_results WHERE run_id=?",
            (run_id,),
        ).fetchone()
        errors = connection.execute(
            """SELECT f.rule_id,f.rule_version,f.record_id,f.field_name,f.field_value,f.error_message
            FROM dq_field_results f WHERE f.run_id=? AND f.test_result=1 ORDER BY f.id""",
            (run_id,),
        ).fetchall()
        remote = connection.execute('SELECT remote_run_id,source_version,revision,reference_versions FROM dq_remote_receipts WHERE local_run_id=?',(run_id,)).fetchone()
        return {
            **run,
            **totals,
            "errors": errors,
            "execution_errors": json.loads(run["execution_errors"]),
            "remote": remote,
        }
    finally:
        connection.close()


def trend_for_table(table):
    connection = get_connection()
    try:
        return connection.execute(
            """SELECT d.rule_id,d.id,d.timestamp,
            100.0*d.passed_count/NULLIF(d.passed_count+d.failed_count,0)
            FROM dq_results d JOIN dq_rules r ON r.id=d.rule_id
            LEFT JOIN dq_runs run ON run.id=d.run_id
            WHERE COALESCE(run.table_name,r.target_table)=? AND r.status='ACTIVE'
            ORDER BY d.timestamp,d.id""",
            (table,),
        ).fetchall()
    finally:
        connection.close()


def export_errors(run_id, path, spreadsheet_safe=True):
    details = run_details(run_id)
    if details is None:
        raise AppError("Run not found.")
    headers = [
        "run_id",
        "rule_id",
        "rule_version",
        "record_id",
        "field_name",
        "field_value",
        "error_message",
    ]
    return write_csv(
        path,
        headers,
        [[run_id, *[row[key] for key in headers[1:]]] for row in details["errors"]],
        spreadsheet_safe,
    )
