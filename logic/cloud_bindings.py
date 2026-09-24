"""Reuse explicit existing dataset mappings when compiling ordinary local SQL."""
import json


def table_bindings(connection, profile, hostname, catalog, schema):
    bindings = {}
    cursor = connection.cursor()
    cursor.row_factory = None
    try:
        rows = cursor.execute('''SELECT r.target_table,l.source_catalog,l.source_schema,
            l.source_table,l.endpoint FROM dq_remote_links l JOIN dq_rules r ON r.id=l.rule_id
            WHERE l.profile=?''',(profile,)).fetchall()
    finally:
        cursor.close()
    for local, source_catalog, source_schema, source_table, endpoint in rows:
        if json.loads(endpoint)[0].lower() != hostname.lower():
            continue
        if source_catalog != catalog or source_schema != schema:
            continue
        parts = [source_catalog,source_schema,source_table]
        if local in bindings and bindings[local] != parts:
            raise ValueError('Conflicting Databricks sources for local table: '+local)
        bindings[local] = parts
    return bindings
