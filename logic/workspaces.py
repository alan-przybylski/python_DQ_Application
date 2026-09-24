"""Environment-scoped views over local report metadata."""
from database.connection import get_connection
from logic.datasets import list_tables


def run_ids(environment=None, profile=None):
    if environment is None and profile is None:
        return None
    c = get_connection()
    try:
        if profile is not None:
            return {row[0] for row in c.execute('''SELECT DISTINCT x.local_run_id
                FROM dq_remote_receipts x JOIN dq_remote_links l ON l.endpoint=x.endpoint
                JOIN dq_rules q ON q.id=l.rule_id AND q.rule_key=x.rule_key WHERE l.profile=?''', (profile,))}
        if environment == 'local':
            return {row[0] for row in c.execute("SELECT id FROM dq_runs WHERE mode != 'databricks'")}
        return {row[0] for row in c.execute('SELECT id FROM dq_runs WHERE mode=?', (environment,))}
    finally:
        c.close()


def report_tables(environment=None, profile=None):
    c = get_connection()
    try:
        if environment == 'databricks':
            query = "SELECT DISTINCT r.target_table FROM dq_rules r JOIN dq_remote_links l ON l.rule_id=r.id WHERE r.execution_mode='databricks'"
            return [r[0] for r in c.execute(query + (' AND l.profile=?' if profile else '') + ' ORDER BY r.target_table', (profile,) if profile else ())]
        if environment == 'local':
            return list_tables(c)
        return sorted(set(list_tables(c)) | {row[0] for row in c.execute('SELECT DISTINCT table_name FROM dq_runs')})
    finally:
        c.close()
