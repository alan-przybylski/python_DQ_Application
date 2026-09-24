from datetime import date, datetime
from decimal import Decimal

import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.databricks_import import local_columns, local_value, Snapshot, Source, save_snapshot
from logic.dataset_types import typed_value, remote_value
from logic.datasets import create_table, table_columns, converted
from logic.table_editor import align_column_types, edit_column, simple_definitions


def test_databricks_types_and_precision_are_retained(sqlite_database):
    columns = local_columns([
        ('product_id','bigint'),('sku','string'),('price','decimal',None,None,10,2),
        ('weight','decimal(8,3)'),('active','boolean'),('launch_date','date'),
        ('updated','timestamp'),('stock','int'),
    ], preserve_names=True)
    assert [c['type'] for c in columns] == ['BIGINT','STRING','DECIMAL(10,2)','DECIMAL(8,3)',
                                           'BOOLEAN','DATE','TIMESTAMP','INT']
    values = [12,'0000123',Decimal('123.40'),Decimal('0.001'),True,date(2026,9,24),datetime(2026,9,24,12,30),5]
    row = tuple(local_value(v,c) for v,c in zip(values,columns))
    source = Source('example.cloud.databricks.com','/sql/1.0/warehouses/abc','workspace','data','products')
    snapshot = Snapshot(source,columns,[row],True)
    save_snapshot(snapshot,'typed_products','Admin')
    c = get_connection()
    assert c.execute('SELECT * FROM typed_products').fetchone() == (1,12,'0000123','123.40','0.001',1,'2026-09-24','2026-09-24T12:30:00',5)
    assert c.execute('SELECT typeof(price),typeof(sku) FROM typed_products').fetchone() == ('text','text')
    assert [col['type'] for col in table_columns('typed_products',c)][1:] == [col['type'] for col in columns]
    simple_definitions(c,'typed_products')
    c.close()
    count, backup = save_snapshot(snapshot,'typed_products','Admin',replace=True)
    assert count == 1 and backup.exists()
    assert remote_value(row[2],columns[2]['type']) == Decimal('123.40')
    assert remote_value(row[5],columns[5]['type']) == date(2026,9,24)


@pytest.mark.parametrize('value,kind',[
    ('2026-02-30','DATE'),('24/09/2026','DATE'),('2026-09-24T12:00:00','DATE'),
    ('2026-09-24','TIMESTAMP'),('2026-09-24T25:00:00','TIMESTAMP'),
    ('2026-09-24T12:00:00+02:00','TIMESTAMP_NTZ'),
    ('1.001','DECIMAL(10,2)'),('100000000.00','DECIMAL(10,2)'),
    (1.2,'DECIMAL(10,2)'),('NaN','DECIMAL(10,2)'),(2,'BOOLEAN'),
])
def test_invalid_temporal_boolean_decimal_values_are_rejected(value,kind):
    with pytest.raises(AppError): typed_value(value,kind)


def test_decimal_38_digits_never_rounds_in_sqlite(sqlite_database):
    value = '123456789012345678901234567890123456.78'
    c = get_connection()
    with c:
        create_table(c,'exact',[{'name':'amount','type':'DECIMAL(38,2)','required':False}])
        c.execute('INSERT INTO exact(amount) VALUES(?)',(typed_value(value,'DECIMAL(38,2)'),))
    assert c.execute('SELECT amount,typeof(amount) FROM exact').fetchone() == (value,'text')
    c.close()


def test_alignment_preserves_ids_values_rules_history_and_sequence(sqlite_database):
    c = get_connection()
    with c:
        c.execute('CREATE TABLE old_products(id INTEGER PRIMARY KEY AUTOINCREMENT,sku TEXT,launch_date TEXT,price TEXT,active INTEGER)')
        c.execute("INSERT INTO old_products VALUES(7,'001','2026-09-24','123.40',1)")
        c.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='old_products'")
        c.execute("INSERT INTO dq_rules(id,version,rule_type,target_table,sql_query) VALUES(50,'1.0','SQL','old_products','SELECT id,sku,0 AS dq_check FROM old_products')")
        c.execute("INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(50,'1.0',1,0)")
    before = c.execute('SELECT * FROM old_products').fetchall()
    history = c.execute('SELECT * FROM dq_results').fetchall()
    rules = c.execute('SELECT * FROM dq_rules').fetchall()
    c.close()
    target = [{'name':n,'type':t} for n,t in [('sku','STRING'),('launch_date','DATE'),('price','DECIMAL(10,2)'),('active','BOOLEAN')]]
    changes, backup = align_column_types('old_products',target)
    assert len(changes) == 4 and backup.exists()
    c = get_connection()
    assert c.execute('SELECT * FROM old_products').fetchall() == before
    assert c.execute('SELECT * FROM dq_rules').fetchall() == rules
    assert c.execute('SELECT * FROM dq_results').fetchall() == history
    assert c.execute("SELECT date(launch_date) FROM old_products").fetchone()[0] == '2026-09-24'
    with c: c.execute("INSERT INTO old_products(sku) VALUES('002')")
    assert c.execute('SELECT MAX(id) FROM old_products').fetchone()[0] == 101
    c.close()
    assert align_column_types('old_products',target) == ([],None)
    # Future editing still works after the multi-column migration.
    edit_column('old_products','add',name='valid_until',kind='DATE')


def test_invalid_alignment_rolls_back_entire_schema(sqlite_database):
    c = get_connection()
    with c:
        c.execute('CREATE TABLE invalid_dates(id INTEGER PRIMARY KEY AUTOINCREMENT,sku TEXT,launch_date TEXT)')
        c.execute("INSERT INTO invalid_dates(sku,launch_date) VALUES('001','2026-02-30')")
    schema = c.execute("SELECT sql FROM sqlite_master WHERE name='invalid_dates'").fetchone()[0]
    c.close()
    with pytest.raises(AppError):
        align_column_types('invalid_dates',[{'name':'sku','type':'STRING'},{'name':'launch_date','type':'DATE'}])
    c = get_connection()
    assert c.execute("SELECT sql FROM sqlite_master WHERE name='invalid_dates'").fetchone()[0] == schema
    assert not c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'dq_edit_%'").fetchall()
    c.close()


def test_csv_validates_dates_decimals_and_boolean():
    assert converted('2024-02-29',{'type':'DATE','required':False}) == '2024-02-29'
    assert converted('true',{'type':'BOOLEAN','required':False}) == 1
    with pytest.raises(AppError): converted('2025-02-29',{'type':'DATE','required':False})
    with pytest.raises(AppError): converted('1.001',{'type':'DECIMAL(10,2)','required':False})
    with pytest.raises(AppError): converted(str(2**31),{'type':'INT','required':False})


def test_explicit_alignment_preserves_dq_anomalies_without_normalizing(sqlite_database):
    c = get_connection()
    with c:
        c.execute('CREATE TABLE anomalies(id INTEGER PRIMARY KEY AUTOINCREMENT,price TEXT,active INTEGER)')
        c.execute('INSERT INTO anomalies(price,active) VALUES(?,?)',("'-99.99",2))
    c.close()
    target = [{'name':'price','type':'DECIMAL(10,2)'},{'name':'active','type':'BOOLEAN'}]
    with pytest.raises(AppError): align_column_types('anomalies',target)
    changes,backup = align_column_types('anomalies',target,preserve_invalid=True)
    assert len(changes) == 2 and backup.exists()
    c = get_connection()
    assert c.execute('SELECT price,active FROM anomalies').fetchone() == ("'-99.99",2)
    c.close()
