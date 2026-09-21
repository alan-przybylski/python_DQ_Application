"""Add rule severity and a durable ticket workflow without changing old results."""


def upgrade_tickets(connection):
    if connection.execute('PRAGMA user_version').fetchone()[0] >= 4:
        return
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        columns = {r[1] for r in connection.execute('PRAGMA table_info(dq_rules)')}
        if 'severity' not in columns:
            connection.execute("ALTER TABLE dq_rules ADD COLUMN severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('low','medium','high'))")
        connection.execute("""CREATE TABLE IF NOT EXISTS dq_tickets (
            id INTEGER PRIMARY KEY,
            rule_id INTEGER REFERENCES dq_rules(id) ON DELETE SET NULL,
            rule_version TEXT,
            table_name TEXT NOT NULL,
            title TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('low','medium','high')),
            status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','in_progress','to_verify','closed','cancelled')),
            reporter TEXT NOT NULL,
            assignee TEXT NOT NULL,
            imported_by TEXT,
            source_file TEXT,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            due_at TEXT NOT NULL,
            closed_at TEXT,
            failed_count INTEGER NOT NULL,
            latest_run_id INTEGER REFERENCES dq_runs(id) ON DELETE SET NULL,
            failure_run_id INTEGER REFERENCES dq_runs(id) ON DELETE SET NULL
        )""")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_dq_ticket ON dq_tickets(rule_id,table_name) WHERE status NOT IN ('closed','cancelled')")
        connection.execute("""CREATE TABLE IF NOT EXISTS dq_ticket_events (
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER NOT NULL REFERENCES dq_tickets(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            actor TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL,
            run_id INTEGER REFERENCES dq_runs(id) ON DELETE SET NULL
        )""")
        connection.execute('PRAGMA user_version=4')
