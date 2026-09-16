-- V1 baseline for the original MySQL import. initialize_database applies
-- additive migrations.py afterwards to add the V2 run-history model.
-- Timestamp strings use local time, matching the original desktop MySQL session.
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT COLLATE MYSQL_AI_CI,
    email TEXT COLLATE MYSQL_AI_CI,
    age INTEGER
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT COLLATE MYSQL_AI_CI NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    role TEXT COLLATE MYSQL_AI_CI DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS data_load_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT COLLATE MYSQL_AI_CI,
    file_name TEXT COLLATE MYSQL_AI_CI,
    row_count INTEGER,
    loaded_by TEXT COLLATE MYSQL_AI_CI,
    loaded_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS dq_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT COLLATE MYSQL_AI_CI DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    activated_at TEXT,
    version TEXT,
    description TEXT COLLATE MYSQL_AI_CI,
    rule_type TEXT COLLATE MYSQL_AI_CI NOT NULL,
    target_table TEXT COLLATE MYSQL_AI_CI NOT NULL,
    error_message TEXT,
    sql_query TEXT
);

CREATE TABLE IF NOT EXISTS dq_rules_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES dq_rules(id),
    version TEXT,
    status TEXT COLLATE MYSQL_AI_CI DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    description TEXT COLLATE MYSQL_AI_CI,
    rule_type TEXT COLLATE MYSQL_AI_CI NOT NULL,
    target_table TEXT COLLATE MYSQL_AI_CI NOT NULL,
    rule_params TEXT,
    deactivated_by TEXT COLLATE MYSQL_AI_CI,
    deactivated_at TEXT
);

CREATE TABLE IF NOT EXISTS dq_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES dq_rules(id),
    rule_version TEXT NOT NULL,
    failed_count INTEGER,
    passed_count INTEGER,
    timestamp TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS dq_field_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES dq_rules(id),
    rule_version TEXT NOT NULL,
    record_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    field_value TEXT,
    test_result INTEGER NOT NULL,
    error_message TEXT,
    timestamp TEXT DEFAULT (datetime('now', 'localtime')),
    target_table TEXT COLLATE MYSQL_AI_CI NOT NULL
);

CREATE INDEX IF NOT EXISTS fk_history_rule ON dq_rules_history(rule_id);
CREATE INDEX IF NOT EXISTS fk_results_rule ON dq_results(rule_id);
CREATE INDEX IF NOT EXISTS fk_field_rule ON dq_field_results(rule_id);
