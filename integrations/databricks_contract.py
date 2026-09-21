"""Versioned wire contract shared by the desktop and the Databricks runner."""

import hashlib
import json
import re

TABLES = {
    'dq_rules': 'rule_key STRING, revision STRING, payload STRING, updated_at TIMESTAMP',
    'dq_runs': 'run_id STRING, rule_key STRING, revision STRING, payload STRING, started_at STRING, completed_at STRING, status STRING, source_version BIGINT, execution_error STRING',
    'dq_results': 'run_id STRING, passed BIGINT, failed BIGINT, field_name STRING',
    'dq_errors': 'run_id STRING, record_id STRING, field_name STRING, field_value STRING, error_message STRING',
}


def name(*parts):
    if any(not isinstance(p, str) or not p or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError('Invalid Databricks identifier.')
    return '.'.join('`' + p.replace('`', '``') + '`' for p in parts)


def canonical(payload):
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def revision(payload):
    return hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()


def template_sql(sql):
    # Strings and quoted identifiers are preserved when stripping comments.
    pattern = r"'(''|[^'])*'|\"(\"\"|[^\"])*\"|`(``|[^`])*`|--[^\n]*|/\*[\s\S]*?\*/"
    cleaned = re.sub(pattern, lambda m: ' ' if m[0].startswith(('--','/*')) else m[0], sql).strip().removesuffix(';').strip()
    tokens = re.sub(pattern, ' ', cleaned)
    if (not re.match(r'^SELECT\b', tokens, re.I) or cleaned.count('{{source}}') != 1
            or len(re.findall(r'\bFROM\b', tokens, re.I)) != 1
            or not re.search(r'\bFROM\s+\{\{source\}\}', tokens, re.I)
            or re.search(r'\b(JOIN|UNION|INTERSECT|EXCEPT)\b|;', tokens, re.I)):
        raise ValueError('Use one SELECT from {{source}}. Joins, subqueries and multiple statements are not supported.')
    # Do not allow extra comma-separated source tables after the source placeholder.
    after = tokens.split('{{source}}', 1)[1]
    source_tail = re.split(r'\b(WHERE|GROUP|ORDER|HAVING|LIMIT|QUALIFY)\b', after, maxsplit=1, flags=re.I)[0]
    if ',' in source_tail:
        raise ValueError('Only the mapped source table is supported.')
    return cleaned


def validate_payload(payload):
    required = {'contract', 'rule_key', 'local_version', 'description', 'rule_type', 'severity', 'error_message', 'active', 'source', 'sql'}
    if set(payload) != required or payload['contract'] != 1:
        raise ValueError('Unsupported Databricks DQ contract.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', payload['rule_key']):
        raise ValueError('Invalid rule key.')
    if payload['severity'] not in ('low','medium','high') or type(payload['active']) is not bool:
        raise ValueError('Invalid severity or active flag.')
    for key in ('local_version','description','rule_type','error_message','sql'):
        if not isinstance(payload[key], str):
            raise ValueError('Rule fields must be text.')
    if not isinstance(payload['source'], list) or len(payload['source']) != 3:
        raise ValueError('Source must contain catalog, schema and table.')
    name(*payload['source'])
    template_sql(payload['sql'])
    return payload
