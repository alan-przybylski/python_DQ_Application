import json

from config.i18n import AppError
from database.connection import get_connection
from logic.dq_engine import validate_rule, error_text
from logic.sql_source import bind_source


def save_rule(description, rule_type, table, sql, message, rule_id=None, severity='medium', cross_spec=None):
    if severity not in ('low', 'medium', 'high'):
        raise AppError('Select Low, Medium or High severity.')
    if not description.strip() or not rule_type.strip():
        raise AppError("Description and rule type are required.")
    sql = bind_source(sql, table)
    validate_rule(sql, table)
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            if rule_id is None:
                return connection.execute(
                    """INSERT INTO dq_rules(description,rule_type,target_table,error_message,sql_query,version,severity,cross_spec)
                    VALUES(?,?,?,?,?,'1.0',?,?)""",
                    (description, rule_type, table, message, sql, severity,json.dumps(cross_spec) if cross_spec else None),
                ).lastrowid
            row = connection.execute(
                "SELECT status,version,cross_spec,sql_query FROM dq_rules WHERE id=?", (rule_id,)
            ).fetchone()
            if not row:
                raise AppError("Rule not found.")
            if row[2] and sql.strip()!=row[3].strip():
                raise ValueError('Create a new cross-table rule in the builder to change its column pairs. Metadata can be edited here.')
            if row[0].upper() == "ACTIVE":
                raise AppError("Deactivate the rule before modifying it.")
            parts = str(row[1] or "1.0").split(".")
            version = f"{parts[0]}.{int(parts[1] if len(parts) > 1 else 0) + 1}"
            connection.execute(
                """UPDATE dq_rules SET description=?,rule_type=?,target_table=?,error_message=?,sql_query=?,version=?,
                status='ACTIVE',activated_at=datetime('now','localtime'),severity=? WHERE id=?""",
                (description, rule_type, table, message, sql, version, severity, rule_id),
            )
            return rule_id
    finally:
        connection.close()


def archive_rule(rule_id, username):
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id,version,created_at,description,rule_type,target_table,error_message,sql_query,severity FROM dq_rules WHERE id=? AND status='ACTIVE'",
                (rule_id,),
            ).fetchone()
            if not row:
                raise AppError("Rule not found.")
            rid, version, created, description, kind, table, error, sql, severity = row
            connection.execute(
                """INSERT INTO dq_rules_history(rule_id,version,status,created_at,description,rule_type,target_table,rule_params,deactivated_by,deactivated_at)
                VALUES(?,?,'INACTIVE',?,?,?,?,?,?,datetime('now','localtime'))""",
                (
                    rid,
                    version,
                    created,
                    description,
                    kind,
                    table,
                    json.dumps(
                        {
                            "sql_query": sql,
                            "description": description,
                            "error_message": error_text(error),
                            "severity": severity,
                        }
                    ),
                    username,
                ),
            )
            connection.execute(
                "UPDATE dq_rules SET status='INACTIVE' WHERE id=?", (rid,)
            )
    finally:
        connection.close()
