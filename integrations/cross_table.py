"""Portable, constrained cross-table rule compiler (SQLite and Spark SQL)."""
import re


def identifier(value):
    if not isinstance(value,str) or not value or any(ord(c)<32 for c in value):
        raise ValueError('Invalid column name.')
    return '`'+value.replace('`','``')+'`'


def validate_spec(spec):
    if set(spec)!={'reference','key','pairs','mode','nulls','normalize','active_column'}:
        raise ValueError('Invalid cross-table configuration.')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',spec['reference']):
        raise ValueError('Reference alias must use lowercase letters, digits and underscores.')
    identifier(spec['key'])
    if spec['mode'] not in ('exists','missing') or spec['nulls'] not in ('fail','skip') or type(spec['normalize']) is not bool:
        raise ValueError('Invalid cross-table options.')
    if not isinstance(spec['pairs'],list) or not 1<=len(spec['pairs'])<=12:
        raise ValueError('Choose between 1 and 12 column pairs.')
    for pair in spec['pairs']:
        if not isinstance(pair,list) or len(pair)!=2:
            raise ValueError('Invalid column pair.')
        for column in pair: identifier(column)
    if spec['pairs'][0][0] in ('id','dq_check'):
        raise ValueError('The first tested column must be a business field, not id or dq_check.')
    if spec['active_column'] is not None: identifier(spec['active_column'])
    return spec


def compile_check(spec, source='{{source}}'):
    validate_spec(spec)
    column=lambda alias,key:alias+'.'+identifier(key)
    def comparable(alias,key):
        value=column(alias,key)
        return 'UPPER(TRIM('+value+'))' if spec['normalize'] else value
    pairs=spec['pairs']
    predicates=[comparable('r',b)+' = '+comparable('p',a) for a,b in pairs]
    if spec['active_column']:
        predicates.append(column('r',spec['active_column'])+' = TRUE')
    nulls=' OR '.join(column('p',a)+' IS NULL' for a,_ in pairs)
    exists=('NOT EXISTS' if spec['mode']=='missing' else 'EXISTS')
    return (f"SELECT {column('p',spec['key'])} AS id, {column('p',pairs[0][0])} AS {identifier(pairs[0][0])},\n"
            f"CASE WHEN {nulls} THEN {0 if spec['nulls']=='skip' else 1}\n"
            f"WHEN {exists} (SELECT 1 FROM {{{{ref:{spec['reference']}}}}} AS r WHERE {' AND '.join(predicates)})\n"
            f"THEN 0 ELSE 1 END AS dq_check\nFROM {source} AS p")
