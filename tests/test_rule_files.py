import json
from pathlib import Path

import pytest

from config.i18n import AppError
from database.connection import get_connection
from logic.rule_files import import_rules, export_rules, validate_files, read_definitions
from logic.rules import save_rule


@pytest.fixture
def account(sqlite_database):
    c = get_connection()
    with c:
        c.execute("INSERT INTO users(username,password_hash,role) VALUES('admin','unused','superuser'),('reader','unused','user')")
    c.close()


def definition(folder, key='name-check', sql='SELECT id,name,0 AS dq_check FROM customers', **changes):
    folder.mkdir(parents=True, exist_ok=True)
    data = {'schema_version': 1, 'key': key, 'description': 'Name required', 'rule_type': 'required',
            'table': 'customers', 'severity': 'high', 'error_message': 'Missing name', 'active': True, 'sql_file': key + '.sql'}
    data.update(changes)
    (folder / (key + '.rule.toml')).write_text('\n'.join(f'{k} = {json.dumps(v)}' for k,v in data.items()), encoding='utf-8')
    (folder / (key + '.sql')).write_text(sql, encoding='utf-8')


def test_import_is_versioned_and_idempotent(account, tmp_path):
    folder = tmp_path / 'rules'
    definition(folder)
    assert validate_files(folder) == {'validated': 1}
    assert import_rules(folder, 'admin') == {'created': 1, 'updated': 0, 'unchanged': 0}
    assert import_rules(folder, 'admin')['unchanged'] == 1
    definition(folder, severity='low', sql='SELECT id,name,1 AS dq_check FROM customers')
    assert import_rules(folder, 'admin')['updated'] == 1
    assert import_rules(folder, 'admin')['unchanged'] == 1
    c = get_connection()
    try:
        assert c.execute('SELECT version,severity,rule_key FROM dq_rules').fetchone() == ('1.1','low','name-check')
        old = json.loads(c.execute('SELECT rule_params FROM dq_rules_history').fetchone()[0])
        assert old['severity'] == 'high' and '0 AS dq_check' in old['sql_query']
        assert c.execute('SELECT COUNT(*) FROM dq_tickets').fetchone()[0] == 0
    finally:
        c.close()


def test_export_round_trip_and_edited_file_protection(account, tmp_path):
    save_rule('Polskie znaki: Żółć', 'test', 'customers', 'SELECT id,name,0 AS dq_check FROM customers', '', severity='low')
    folder = tmp_path / 'export'
    assert export_rules(folder, 'admin')['exported'] == 1
    assert export_rules(folder, 'admin')['exported'] == 1
    assert import_rules(folder, 'admin')['unchanged'] == 1
    sql = next(folder.glob('*.sql'))
    sql.write_text('edited', encoding='utf-8')
    with pytest.raises(AppError):
        export_rules(folder, 'admin')
    assert sql.read_text() == 'edited'


def test_import_rolls_back_all_rules(account, tmp_path):
    folder = tmp_path / 'rules'
    definition(folder, 'a-good')
    definition(folder, 'z-bad', sql='DELETE FROM customers')
    with pytest.raises(Exception):
        import_rules(folder, 'admin')
    c = get_connection()
    assert c.execute('SELECT COUNT(*) FROM dq_rules').fetchone()[0] == 0
    c.close()


def test_permissions_and_path_validation(account, tmp_path):
    folder = tmp_path / 'rules'
    definition(folder)
    with pytest.raises(AppError):
        import_rules(folder, 'reader')
    with pytest.raises(AppError):
        export_rules(tmp_path/'export', 'reader')
    definition(folder, sql_file='../outside.sql')
    with pytest.raises(AppError):
        read_definitions(folder)


def test_examples_validate(account):
    assert validate_files(Path(__file__).resolve().parents[1] / 'rules') == {'validated': 2}


def test_deactivation_and_missing_files_are_explicit(account, tmp_path):
    folder = tmp_path / 'rules'
    definition(folder)
    definition(folder, 'other')
    import_rules(folder, 'admin')
    (folder / 'other.rule.toml').unlink()
    definition(folder, active=False)
    import_rules(folder, 'admin')
    c = get_connection()
    assert c.execute('SELECT rule_key,status FROM dq_rules ORDER BY rule_key').fetchall() == [('name-check','INACTIVE'),('other','ACTIVE')]
    c.close()
