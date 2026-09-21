def upgrade_references(c):
    if c.execute('PRAGMA user_version').fetchone()[0]>=7:
        return
    with c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS dq_references (alias TEXT PRIMARY KEY, local_table TEXT NOT NULL, profile TEXT NOT NULL, catalog TEXT NOT NULL, schema_name TEXT NOT NULL, table_name TEXT NOT NULL)')
        if 'cross_spec' not in {r[1] for r in c.execute('PRAGMA table_info(dq_rules)')}:
            c.execute('ALTER TABLE dq_rules ADD COLUMN cross_spec TEXT')
        if 'reference_versions' not in {r[1] for r in c.execute('PRAGMA table_info(dq_remote_receipts)')}:
            c.execute('ALTER TABLE dq_remote_receipts ADD COLUMN reference_versions TEXT')
        c.execute('PRAGMA user_version=7')
