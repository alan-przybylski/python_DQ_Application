"""Explicit hard deletion of one rule and its dependent history, atomically."""

import json

from config.i18n import AppError
from database.connection import get_connection
from logic.accounts import require_superuser


def delete_rule(rule_id, username, expected_version=None):
    connection = get_connection()
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            require_superuser(connection, username)
            rule = connection.execute(
                "SELECT id,version FROM dq_rules WHERE id=?", (rule_id,)
            ).fetchone()
            if not rule:
                raise AppError("Rule not found.")
            rule_id = rule[0]
            if expected_version is not None and rule[1] != expected_version:
                raise AppError(
                    "The rule changed. Reopen its details before deleting it."
                )
            affected = {
                row[0]
                for row in connection.execute(
                    "SELECT run_id FROM dq_results WHERE rule_id=? AND run_id IS NOT NULL "
                    "UNION SELECT run_id FROM dq_field_results WHERE rule_id=? AND run_id IS NOT NULL",
                    (rule_id, rule_id),
                )
            }
            runs = []
            for rid, status, requested, completed, raw in connection.execute(
                "SELECT id,status,rules_requested,rules_completed,execution_errors FROM dq_runs"
            ):
                try:
                    errors = json.loads(raw)
                    if not isinstance(errors, list) or any(
                        not isinstance(item, dict) or "rule_id" not in item
                        for item in errors
                    ):
                        raise ValueError
                except (ValueError, TypeError):
                    raise AppError(
                        "Run history cannot be verified. Nothing was deleted."
                    ) from None
                remaining = [e for e in errors if str(e["rule_id"]) != str(rule_id)]
                if rid not in affected and len(remaining) == len(errors):
                    continue
                actual = connection.execute(
                    "SELECT COUNT(DISTINCT rule_id) FROM dq_results WHERE run_id=?",
                    (rid,),
                ).fetchone()[0]
                if (
                    status == "running"
                    or completed != actual
                    or requested != actual + len(errors)
                ):
                    raise AppError(
                        "Run history cannot be verified. Nothing was deleted."
                    )
                runs.append((rid, remaining))

            connection.execute(
                "DELETE FROM dq_field_results WHERE rule_id=?", (rule_id,)
            )
            connection.execute("DELETE FROM dq_results WHERE rule_id=?", (rule_id,))
            connection.execute(
                "DELETE FROM dq_rules_history WHERE rule_id=?", (rule_id,)
            )
            from logic.tickets import event

            for (ticket_id,) in connection.execute(
                "SELECT id FROM dq_tickets WHERE rule_id=? AND status NOT IN ('closed','cancelled')", (rule_id,)
            ).fetchall():
                connection.execute("UPDATE dq_tickets SET status='cancelled',closed_at=datetime('now','localtime') WHERE id=?", (ticket_id,))
                event(connection, ticket_id, username, 'rule_deleted', str(rule_id))
            connection.execute("DELETE FROM dq_rules WHERE id=?", (rule_id,))
            for rid, errors in runs:
                completed = connection.execute(
                    "SELECT COUNT(DISTINCT rule_id) FROM dq_results WHERE run_id=?",
                    (rid,),
                ).fetchone()[0]
                fields = connection.execute(
                    "SELECT COUNT(*) FROM dq_field_results WHERE run_id=?", (rid,)
                ).fetchone()[0]
                if not completed and not errors and not fields:
                    connection.execute("DELETE FROM dq_runs WHERE id=?", (rid,))
                else:
                    status = (
                        "partial"
                        if errors and completed
                        else "failed"
                        if errors
                        else "completed"
                    )
                    connection.execute(
                        "UPDATE dq_runs SET rules_requested=?,rules_completed=?,status=?,execution_errors=? WHERE id=?",
                        (
                            completed + len(errors),
                            completed,
                            status,
                            json.dumps(errors, ensure_ascii=False),
                            rid,
                        ),
                    )
    finally:
        connection.close()
