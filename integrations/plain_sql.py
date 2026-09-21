"""Parse ordinary SELECT SQL; bind dataset tables without user-facing aliases."""
import sqlglot
from sqlglot import exp, ErrorLevel
from sqlglot.optimizer.scope import traverse_scope


def parsed(sql,dialect):
    statements=sqlglot.parse(sql,read=dialect)
    if len(statements)!=1 or not isinstance(statements[0],exp.Query):
        raise ValueError('Use a single SELECT query.')
    tree=statements[0]
    forbidden=(exp.Insert,exp.Update,exp.Delete,exp.Create,exp.Drop,exp.Command,exp.Into)
    if any(isinstance(node,forbidden) for node in tree.walk()):
        raise ValueError('Only read-only SELECT queries are supported.')
    physical=[]
    for scope in traverse_scope(tree):
        for _,source in scope.selected_sources.values():
            if isinstance(source,exp.Table):
                if not isinstance(source.this,exp.Identifier) or source.args.get('version'):
                    raise ValueError('Use dataset tables, without table functions or explicit time travel.')
                physical.append(source)
            elif not hasattr(source,'expression'):
                raise ValueError('Unsupported table source.')
    if not physical:
        raise ValueError('The query must read a dataset table.')
    return tree,physical


def compile_sql(sql,catalog,schema,allowed):
    tree,tables=parsed(sql,'sqlite')
    available={name.casefold():name for name in allowed}
    dependencies={}
    for table in tables:
        if table.db or table.catalog or table.name.casefold() not in available:
            raise ValueError('Unknown local table: '+table.sql())
        local=available[table.name.casefold()]
        dependencies[local]=[catalog,schema,local]
        table.set('this',exp.to_identifier(local,quoted=True))
        table.set('db',exp.to_identifier(schema,quoted=True))
        table.set('catalog',exp.to_identifier(catalog,quoted=True))
    rendered=tree.sql(dialect='databricks',unsupported_level=ErrorLevel.RAISE)
    validate_sql(rendered,dependencies)
    return rendered,dependencies


def validate_sql(sql,dependencies):
    tree,tables=parsed(sql,'databricks')
    allowed={tuple(parts) for parts in dependencies.values()}
    found={(t.catalog,t.db,t.name) for t in tables}
    if found!=allowed:
        raise ValueError('SQL tables do not match the declared datasets.')
    return tree,tables


def versioned_sql(sql,dependencies,versions):
    tree,tables=validate_sql(sql,dependencies)
    by_table={tuple(parts):alias for alias,parts in dependencies.items()}
    for table in tables:
        version=versions[by_table[(table.catalog,table.db,table.name)]]
        if type(version) is not int or version<0:
            raise ValueError('Invalid table snapshot version.')
        table.set('version',exp.Version(this='VERSION',expression=exp.Literal.number(version),kind='AS OF'))
    return tree.sql(dialect='databricks',unsupported_level=ErrorLevel.RAISE)
