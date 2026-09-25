"""Project native drafts and older linked publications into one cloud library."""
import json

from database.connection import get_connection, dict_row_factory
from integrations.databricks_contract import name, revision, validate_payload, template_sql
from logic.databricks_sync import definition


def list_cloud_rules(profile):
    c = get_connection()
    c.row_factory = dict_row_factory
    try:
        rules = c.execute('''SELECT r.*,l.id AS link_id,l.base_revision,l.profile FROM dq_rules r
            JOIN dq_remote_links l ON l.rule_id=r.id WHERE l.profile=? ORDER BY r.id''', (profile,)).fetchall()
        for rule in rules:
            published = c.execute('SELECT payload FROM dq_remote_versions WHERE link_id=? AND revision=?',
                                  (rule['link_id'], rule['base_revision'])).fetchone()
            legacy = rule['sql_engine'] != 'databricks'
            # A linked rule's local SQL may differ from its published cloud SQL.
            # Show the saved publication, never pass SQLite SQL to the cloud editor.
            if legacy and published:
                payload = validate_payload(json.loads(published['payload']))
                if revision(payload) != rule['base_revision']:
                    raise ValueError('Saved publication checksum does not match its revision.')
            else:
                _, payload = definition(rule['link_id'])
            rule['publication_state'] = ('Published' if rule['base_revision'] == revision(payload)
                                         else 'Pending publication' if rule['base_revision'] else 'Draft')
            sql = payload['sql'] if legacy else rule['sql_query']
            if legacy and payload['contract'] != 3:
                sql = template_sql(sql, payload.get('cross_spec')).replace('{{source}}', name(*payload['source']))
                for alias, parts in payload.get('references', {}).items():
                    sql = sql.replace('{{ref:' + alias + '}}', name(*parts))
            rule.update(display_sql=sql, cloud_table=name(*payload['source']),
                        display_active=payload['active'], display_version=payload['local_version'],
                        display_description=payload['description'])
        return rules
    finally:
        c.close()


def list_library_rules(environment=None, profile=None):
    """One row per rule, classified by its execution environment."""
    from logic.rule_library import list_rules
    from logic.databricks_sync import mappings
    profiles = {link['profile'] for link in mappings()}
    cloud = {rule['id']: rule for key in profiles for rule in list_cloud_rules(key)}
    output = []
    for rule in list_rules():
        remote = rule['sql_engine'] == 'databricks' or rule['execution_mode'] == 'databricks'
        kind = 'databricks' if remote else 'local'
        if environment is not None and environment != kind:
            continue
        if remote and rule['id'] in cloud:
            item = cloud[rule['id']]
        else:
            item = {**rule, 'display_description': rule['description'], 'display_sql': rule['sql_query'],
                    'display_active': rule['status'] == 'ACTIVE', 'display_version': rule['version'],
                    'cloud_table': rule['target_table'], 'publication_state': '—', 'profile': ''}
        if profile is not None and item['profile'] != profile:
            continue
        output.append({**item, 'environment': kind})
    return output
