"""Remote rule mappings and a persistent, idempotent run receipt ledger."""


def upgrade_databricks_sync(c):
    if c.execute('PRAGMA user_version').fetchone()[0] >= 6:
        return
    with c:
        c.execute('BEGIN IMMEDIATE')
        if 'execution_mode' not in {r[1] for r in c.execute('PRAGMA table_info(dq_rules)')}:
            c.execute("ALTER TABLE dq_rules ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'local' CHECK(execution_mode IN ('local','databricks'))")
        c.execute('''CREATE TABLE IF NOT EXISTS dq_remote_links (
            id INTEGER PRIMARY KEY, rule_id INTEGER NOT NULL UNIQUE REFERENCES dq_rules(id) ON DELETE CASCADE,
            profile TEXT NOT NULL, control_catalog TEXT NOT NULL, control_schema TEXT NOT NULL,
            source_catalog TEXT NOT NULL, source_schema TEXT NOT NULL, source_table TEXT NOT NULL,
            remote_sql TEXT NOT NULL, endpoint TEXT NOT NULL, base_revision TEXT,
            auto_sync INTEGER NOT NULL DEFAULT 0, owner TEXT NOT NULL,
            last_sync TEXT, last_error TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS dq_remote_versions (
            link_id INTEGER NOT NULL REFERENCES dq_remote_links(id) ON DELETE CASCADE,
            revision TEXT NOT NULL, local_version TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY(link_id,revision)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS dq_remote_receipts (
            endpoint TEXT NOT NULL, remote_run_id TEXT NOT NULL,
            local_run_id INTEGER REFERENCES dq_runs(id) ON DELETE SET NULL,
            source_version INTEGER, rule_key TEXT NOT NULL, revision TEXT NOT NULL,
            PRIMARY KEY(endpoint,remote_run_id)
        )''')
        c.execute('PRAGMA user_version=6')
