def upgrade_plain_sql(c):
    if c.execute('PRAGMA user_version').fetchone()[0]>=8:
        return
    with c:
        if 'plain_sql' not in {r[1] for r in c.execute('PRAGMA table_info(dq_remote_links)')}:
            c.execute('ALTER TABLE dq_remote_links ADD COLUMN plain_sql INTEGER NOT NULL DEFAULT 0')
        c.execute('PRAGMA user_version=8')
