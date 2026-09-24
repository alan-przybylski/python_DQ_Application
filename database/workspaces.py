"""Keep SQL dialect independent of legacy publication state."""
from datetime import datetime
from pathlib import Path


def upgrade_workspaces(connection, destination):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(dq_rules)')}
    if 'sql_engine' in columns:
        return
    if connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]:
        from database.connection import get_connection
        destination = Path(destination)
        directory = destination.parent / 'backups'
        directory.mkdir(parents=True, exist_ok=True)
        backup = get_connection(directory / f'{destination.stem}_before_workspaces_{datetime.now():%Y%m%d_%H%M%S_%f}.db')
        try:
            connection.backup(backup)
        finally:
            backup.close()
    with connection:
        connection.execute("ALTER TABLE dq_rules ADD COLUMN sql_engine TEXT NOT NULL DEFAULT 'sqlite' CHECK(sql_engine IN ('sqlite','databricks'))")
        connection.execute('PRAGMA user_version=9')
