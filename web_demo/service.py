"""Synthetic datasets and session-owned storage; no global database switching."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from database.connection import get_connection, initialize_database
from logic.dq_engine import evaluate, run_checks
from logic.sql_source import bind_source

TABLES = {
    "customers": ("id", "name", "email", "age"),
    "products": ("id", "sku", "name", "price", "launch_date"),
}

CLEAN_CUSTOMERS = tuple(
    (i, name, f"customer{i}@example.test", 20 + i * 3)
    for i, name in enumerate(
        ("Alex Demo", "Morgan Sample", "Taylor Test", "Jordan Example",
         "Casey Demo", "Riley Sample", "Avery Test", "Jamie Example",
         "Robin Demo", "Quinn Sample", "Sam Test", "Charlie Example"), 1
    )
)
CLEAN_PRODUCTS = tuple(
    (i, f"SKU-{i:03}", name, round(9.99 + i * 5, 2), f"2026-09-{i:02}")
    for i, name in enumerate(
        ("Wireless headphones", "Bluetooth speaker", "Desk lamp", "Travel mug",
         "Keyboard", "Mouse", "Notebook", "Backpack", "USB cable",
         "Water bottle", "Phone stand", "Laptop sleeve"), 1
    )
)


def dirty_rows(table):
    if table == "customers":
        rows = [list(row) for row in CLEAN_CUSTOMERS]
        rows[1][2] = "missing-at.example.test"
        rows[3][3] = 15
        rows[5][1] = ""
        rows[7][2] = rows[0][2]
        rows[9][3] = 145
        rows[11][2] = None
    else:
        rows = [list(row) for row in CLEAN_PRODUCTS]
        rows[1][1] = rows[0][1]
        rows[3][3] = -9.99
        rows[5][2] = ""
        rows[7][4] = "2026-02-30"
        rows[9][3] = 0
        rows[11][4] = None
    return rows


# Each query returns a row-level check: 0 = PASS, 1 = FAIL.
RULES = (
    (1, "customers", "Customer name required", "Completeness", "name", "Name must not be empty.", "LENGTH(TRIM(name)) > 0"),
    (2, "customers", "Email format", "Validity", "email", "Email must contain @ and a domain suffix.", "email LIKE '%_@_%._%'"),
    (3, "customers", "Age between 18 and 120", "Range", "age", "Age must be between 18 and 120.", "age BETWEEN 18 AND 120"),
    (4, "customers", "Email uniqueness", "Uniqueness", "email", "Email must be present and unique.", "email IS NOT NULL AND TRIM(email) <> '' AND COUNT(*) OVER (PARTITION BY LOWER(TRIM(email))) = 1"),
    (5, "products", "SKU uniqueness", "Uniqueness", "sku", "SKU must be present and unique.", "sku IS NOT NULL AND TRIM(sku) <> '' AND COUNT(*) OVER (PARTITION BY LOWER(TRIM(sku))) = 1"),
    (6, "products", "Product name required", "Completeness", "name", "Product name must not be empty.", "LENGTH(TRIM(name)) > 0"),
    (7, "products", "Price greater than zero", "Range", "price", "Price must be a positive number.", "TYPEOF(price) IN ('integer','real') AND price > 0"),
    (8, "products", "Valid launch date", "Validity", "launch_date", "Launch date must be a valid YYYY-MM-DD date.", "LENGTH(launch_date) = 10 AND launch_date = DATE(launch_date, '+0 days')"),
)


class DemoSession:
    """One temporary directory per browser session; cleaned up when released."""

    def __init__(self):
        self.directory = TemporaryDirectory(prefix="dq-web-demo-")
        self.database = Path(self.directory.name) / "demo.db"
        self.revision = 0
        initialize_database(self.database)
        with closing(get_connection(self.database)) as connection, connection:
            connection.execute(
                "CREATE TABLE products(id INTEGER PRIMARY KEY, sku TEXT, name TEXT, price REAL, launch_date DATE)"
            )
            # This account is internal to the anonymous synthetic session, not a login.
            connection.execute(
                "INSERT INTO users(username,password_hash,role) VALUES('demo','disabled','user')"
            )
            for rid, table, title, kind, field, message, condition in RULES:
                sql = f"SELECT id, {field}, CASE WHEN {condition} THEN 0 ELSE 1 END AS dq_check FROM {table}"
                connection.execute(
                    """INSERT INTO dq_rules(id,version,description,rule_type,target_table,error_message,sql_query)
                    VALUES(?,'1.0',?,?,?,?,?)""",
                    (rid, title, kind, table, message, sql),
                )
            for table in TABLES:
                self._replace(connection, table, dirty_rows(table))
        # Populate an actual baseline report using the same engine as desktop.
        for table in TABLES:
            self.run(table)

    def close(self):
        self.directory.cleanup()

    def query(self, sql, parameters=()):
        with closing(get_connection(self.database)) as connection:
            cursor = connection.execute(sql, parameters)
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    @staticmethod
    def _replace(connection, table, rows):
        if table not in TABLES:
            raise ValueError("Unknown demo table.")
        columns = TABLES[table]
        rows = list(rows)
        if len(rows) != 12 or any(len(row) != len(columns) for row in rows):
            raise ValueError("Keep the 12 demo records and their existing columns.")
        if {row[0] for row in rows} != set(range(1, 13)):
            raise ValueError("Demo record IDs must stay between 1 and 12.")
        if any(isinstance(value, str) and len(value) > 500 for row in rows for value in row):
            raise ValueError("Demo values are limited to 500 characters.")
        connection.execute(f'DELETE FROM "{table}"')
        connection.executemany(
            f'INSERT INTO "{table}" VALUES({",".join("?" for _ in columns)})', rows
        )

    def save_rows(self, table, rows):
        with closing(get_connection(self.database)) as connection, connection:
            self._replace(connection, table, rows)
        self.revision += 1

    def clean(self, table):
        self.save_rows(table, CLEAN_CUSTOMERS if table == "customers" else CLEAN_PRODUCTS)

    def run(self, table, rule_id=None):
        if table not in TABLES:
            raise ValueError("Unknown demo table.")
        if self.query("SELECT COUNT(*) AS count FROM dq_runs")[0]["count"] >= 100:
            raise ValueError("This session has reached 100 runs. Reset demo to continue.")
        return run_checks(table, "demo", rule_id, database=self.database)

    def preview(self, sql, table):
        if len(sql) > 10_000:
            raise ValueError("SQL preview is limited to 10,000 characters.")
        with closing(get_connection(self.database)) as connection:
            connection.execute("PRAGMA query_only=ON")
            _, records = evaluate(connection, bind_source(sql, table), TABLES, max_records=500)
            return records

    def rules(self, table):
        return self.query("SELECT * FROM dq_rules WHERE target_table=? ORDER BY id", (table,))

    def runs(self, table):
        return self.query(
            """SELECT r.id, r.started_at, r.status, r.rules_completed,
            COALESCE(SUM(d.passed_count),0) AS passed,
            COALESCE(SUM(d.failed_count),0) AS failed
            FROM dq_runs r LEFT JOIN dq_results d ON d.run_id=r.id
            WHERE r.table_name=? GROUP BY r.id ORDER BY r.id DESC""", (table,)
        )

    def report(self, run_id):
        return self.query(
            """SELECT q.description AS rule, d.rule_version AS version,
            d.passed_count AS passed, d.failed_count AS failed
            FROM dq_results d JOIN dq_rules q ON q.id=d.rule_id
            WHERE d.run_id=? ORDER BY q.id""", (run_id,)
        )

    def failures(self, run_id):
        return self.query(
            """SELECT q.description AS rule, f.record_id, f.field_name,
            f.field_value, f.error_message
            FROM dq_field_results f JOIN dq_rules q ON q.id=f.rule_id
            WHERE f.run_id=? AND f.test_result=1 ORDER BY f.id""", (run_id,)
        )
