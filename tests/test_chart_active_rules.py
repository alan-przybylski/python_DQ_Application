from database.connection import get_connection
from logic.dq_engine import trend_for_table


def test_chart_only_shows_active_rules_without_deleting_history(sqlite_database):
    connection = get_connection()
    try:
        with connection:
            connection.executemany(
                "INSERT INTO dq_rules(id,version,status,rule_type,target_table) VALUES(?,'1.0',?,'test',?)",
                [(1, 'ACTIVE', 'customers'), (2, 'INACTIVE', 'customers'), (3, 'ACTIVE', 'other')],
            )
            connection.executemany(
                "INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(?,'1.0',8,2)",
                [(1,), (2,), (3,)],
            )
        before = connection.execute('SELECT * FROM dq_results ORDER BY id').fetchall()
        assert [row[0] for row in trend_for_table('customers')] == [1]
        with connection:
            connection.execute("UPDATE dq_rules SET status='INACTIVE' WHERE id=1")
        assert trend_for_table('customers') == []
        with connection:
            connection.execute("UPDATE dq_rules SET status='ACTIVE' WHERE id=2")
        assert [row[0] for row in trend_for_table('customers')] == [2]
        assert connection.execute('SELECT * FROM dq_results ORDER BY id').fetchall() == before
    finally:
        connection.close()
