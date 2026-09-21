"""Stable identities for portable rule definitions."""


def upgrade_rule_files(connection):
    if connection.execute('PRAGMA user_version').fetchone()[0] >= 5:
        return
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        if 'rule_key' not in {row[1] for row in connection.execute('PRAGMA table_info(dq_rules)')}:
            connection.execute('ALTER TABLE dq_rules ADD COLUMN rule_key TEXT')
        connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS rule_file_identity ON dq_rules(rule_key)')
        connection.execute('PRAGMA user_version=5')
