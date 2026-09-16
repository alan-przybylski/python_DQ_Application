"""Create an isolated, repeatable demo. Never reset or overwrite existing data."""

import argparse
import csv
from pathlib import Path

import bcrypt

from config.paths import DATA_DIR, DATABASE_PATH, PROJECT_DIR
from database.connection import dict_row_factory, get_connection, initialize_database

DEMO_APPLICATION_ID = 1146176333
DEMO_USERNAME = "demo"
# Public credentials for the synthetic demo ONLY. Never used in the private app DB.
DEMO_PASSWORD = "demo-only-2026"
RULES = (
    (1, "Email format", "format", "Email must contain @ and a domain suffix.",
     "SELECT id, email, CASE WHEN email LIKE '%_@_%._%' THEN 1 ELSE 0 END AS dq_check FROM customers"),
    (2, "Age range: 18–120", "range", "Age must be between 18 and 120.",
     "SELECT id, age, CASE WHEN age BETWEEN 18 AND 120 THEN 1 ELSE 0 END AS dq_check FROM customers"),
    (3, "Customer name required", "completeness", "Customer name must not be empty.",
     "SELECT id, name, CASE WHEN LENGTH(TRIM(name)) > 0 THEN 1 ELSE 0 END AS dq_check FROM customers"),
)


def read_sample(name):
    with (PROJECT_DIR / "samples" / name).open(encoding="utf-8", newline="") as stream:
        return [(int(row["id"]), row["name"] or None, row["email"] or None,
                 int(row["age"]) if row["age"] else None)
                for row in csv.DictReader(stream, delimiter=";")]


def create_demo_database(destination=None):
    destination = Path(destination or DATA_DIR / "demo.db").resolve()
    if destination == DATABASE_PATH.resolve():
        raise ValueError("Demo data must never be written to the private application database.")
    if destination.exists():
        connection = get_connection(destination)
        try:
            if connection.execute("PRAGMA application_id").fetchone()[0] != DEMO_APPLICATION_ID:
                raise FileExistsError("Existing file is not a DQ demo database; left unchanged.")
        finally:
            connection.close()
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive file creation prevents accidentally replacing another process's database.
    with destination.open("xb"):
        pass
    initialize_database(destination)
    connection = get_connection(destination)
    try:
        with connection:
            connection.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)", (
                DEMO_USERNAME, bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode("ascii"), "admin"))
            for rule_id, description, rule_type, error, sql in RULES:
                connection.execute("""INSERT INTO dq_rules(id,version,description,rule_type,target_table,error_message,sql_query)
                                      VALUES(?,'1.0',?,?,'customers',?,?)""",
                                   (rule_id, description, rule_type, error, sql))

            dirty = read_sample("customers_with_issues.csv")
            clean = read_sample("customers_clean.csv")
            partial = [clean_row if dirty_row[0] <= 6 else dirty_row
                       for dirty_row, clean_row in zip(dirty, clean)]
            batches = ((dirty, "2026-09-01 09:00:00", "customers_with_issues.csv"),
                       (partial, "2026-09-02 09:00:00", "synthetic_partial_cleanup.csv"),
                       (clean, "2026-09-03 09:00:00", "customers_clean.csv"))
            for rows, timestamp, filename in batches:
                connection.executemany("""INSERT INTO customers(id,name,email,age) VALUES(?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,email=excluded.email,age=excluded.age""", rows)
                connection.execute("""INSERT INTO data_load_log(table_name,file_name,row_count,loaded_by,loaded_at)
                    VALUES('customers',?,?,?,?)""", (filename, len(rows), DEMO_USERNAME, timestamp))
                for rule_id, _, _, error, sql in RULES:
                    cursor = connection.cursor()
                    cursor.row_factory = dict_row_factory
                    records = cursor.execute(sql).fetchall()
                    cursor.close()
                    passed = sum(record["dq_check"] for record in records)
                    connection.execute("""INSERT INTO dq_results(rule_id,rule_version,failed_count,passed_count,timestamp)
                        VALUES(?,'1.0',?,?,?)""", (rule_id, len(records) - passed, passed, timestamp))
                    for record in records:
                        field = list(record)[1]
                        connection.execute("""INSERT INTO dq_field_results
                            (rule_id,rule_version,record_id,field_name,field_value,test_result,error_message,timestamp,target_table)
                            VALUES(?,'1.0',?,?,?,?,?,?,'customers')""", (
                                rule_id, str(record["id"]), field,
                                str(record[field]) if record[field] is not None else None,
                                record["dq_check"], "" if record["dq_check"] else error, timestamp))
            connection.execute(f"PRAGMA application_id = {DEMO_APPLICATION_ID}")
    finally:
        connection.close()
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATA_DIR / "demo.db")
    args = parser.parse_args()
    print(f"Demo ready: {create_demo_database(args.database)}")
    print(f"Public demo login: {DEMO_USERNAME} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
