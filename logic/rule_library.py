"""Read-only projections for the rule library; no history/schema migrations."""

import json

from config.i18n import AppError
from database.connection import get_connection, dict_row_factory


def list_rules():
    connection = get_connection()
    connection.row_factory = dict_row_factory
    try:
        return connection.execute("""
            SELECT r.*, d.id AS result_id, d.timestamp AS result_time,
                   d.passed_count, d.failed_count, d.run_id,
                   100.0*d.passed_count/NULLIF(d.passed_count+d.failed_count,0) AS kpi
            FROM dq_rules r
            LEFT JOIN dq_results d ON d.id=(
                SELECT x.id FROM dq_results x
                WHERE x.rule_id=r.id AND x.rule_version IS r.version
                ORDER BY x.timestamp DESC,x.id DESC LIMIT 1)
            ORDER BY r.id
        """).fetchall()
    finally:
        connection.close()


def rule_details(rule_id):
    connection = get_connection()
    connection.row_factory = dict_row_factory
    try:
        connection.execute("BEGIN")
        current = connection.execute(
            "SELECT * FROM dq_rules WHERE id=?", (rule_id,)
        ).fetchone()
        if current is None:
            raise AppError("Rule not found.")
        history = connection.execute(
            "SELECT * FROM dq_rules_history WHERE rule_id=? ORDER BY history_id DESC",
            (rule_id,),
        ).fetchall()
        versions = [
            {
                **current,
                "current": True,
                "event_time": current["activated_at"] or current["created_at"],
            }
        ]
        if current["status"] == "INACTIVE":
            archived = next(
                (row for row in history if row["version"] == current["version"]), None
            )
            if archived:
                versions[0]["event_time"] = (
                    archived["deactivated_at"] or versions[0]["event_time"]
                )
        seen = {current["version"]}
        for row in history:
            if row["version"] in seen:
                continue
            seen.add(row["version"])
            try:
                params = json.loads(row["rule_params"] or "{}")
                if not isinstance(params, dict):
                    params = {}
            except (ValueError, TypeError):
                params = {}
            historical_sql = params.get("sql_query")
            versions.append(
                {
                    **row,
                    "current": False,
                    "event_time": row["deactivated_at"] or row["created_at"],
                    "sql_query": historical_sql
                    if isinstance(historical_sql, str)
                    else None,
                    "error_message": params.get("error_message"),
                    "severity": params.get("severity", "medium"),
                }
            )
        result = connection.execute(
            "SELECT * FROM dq_results WHERE rule_id=? AND rule_version IS ? ORDER BY timestamp DESC,id DESC LIMIT 1",
            (rule_id, current["version"]),
        ).fetchone()
        errors = []
        if result and result["run_id"] is not None:
            errors = connection.execute(
                "SELECT record_id,field_name,field_value,error_message FROM dq_field_results WHERE run_id=? AND rule_id=? AND rule_version IS ? AND test_result=1 ORDER BY id LIMIT 500",
                (result["run_id"], rule_id, current["version"]),
            ).fetchall()
        return {
            "current": current,
            "versions": versions,
            "result": result,
            "errors": errors,
        }
    finally:
        connection.close()
