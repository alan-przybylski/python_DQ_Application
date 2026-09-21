"""Spark runner. Imports no desktop, SQLite or Tk code; Python 3.10+ compatible."""

from datetime import datetime, timezone
import json
import uuid

from integrations.databricks_contract import TABLES, name, canonical, revision, validate_payload, template_sql


def setup(spark, catalog, schema):
    spark.sql('CREATE SCHEMA IF NOT EXISTS ' + name(catalog,schema))
    for table, fields in TABLES.items():
        spark.sql(f'CREATE TABLE IF NOT EXISTS {name(catalog,schema,table)} ({fields}) USING DELTA')


def run_job(spark, catalog, schema):
    from pyspark.sql import functions as F
    from pyspark.sql.types import ByteType, ShortType, IntegerType, LongType
    spark.conf.set('spark.sql.session.timeZone','UTC')
    prefix = (catalog,schema)
    rules = spark.table(name(*prefix,'dq_rules')).collect()
    keys = [r['rule_key'] for r in rules]
    if len(keys)!=len(set(keys)):
        raise ValueError('Duplicate rule keys in dq_rules.')
    failures = []
    for row in rules:
        payload = validate_payload(json.loads(row['payload']))
        if revision(payload)!=row['revision'] or payload['rule_key']!=row['rule_key']:
            raise ValueError('Rule checksum mismatch. Publish definitions through DQ Studio.')
        if not payload['active']:
            continue
        run_id = uuid.uuid4().hex
        started = datetime.now(timezone.utc).isoformat()
        run = {'run_id':run_id,'rule_key':row['rule_key'],'revision':row['revision'],'payload':canonical(payload),
               'started_at':started,'completed_at':None,'status':'running','source_version':None,'execution_error':None}
        spark.createDataFrame([run], TABLES['dq_runs']).write.mode('append').saveAsTable(name(*prefix,'dq_runs'))
        stage = name(*prefix,'dq_stage_'+run_id)
        try:
            source = name(*payload['source'])
            version = int(spark.sql(f'DESCRIBE HISTORY {source} LIMIT 1').first()['version'])
            query = template_sql(payload['sql']).replace('{{source}}', f'{source} VERSION AS OF {version}')
            # Subquery position disallows DML/DDL even if a definition was edited externally.
            checked = spark.sql('SELECT * FROM (\n'+query+'\n) dq_checked')
            columns = checked.columns
            if len(columns)<3 or columns[0]!='id' or columns[1] in ('id','dq_check') or 'dq_check' not in columns or len(set(columns))!=len(columns):
                raise ValueError('Return id, the checked field second, and dq_check.')
            if not isinstance(checked.schema['dq_check'].dataType,(ByteType,ShortType,IntegerType,LongType)):
                raise ValueError('dq_check must be an integer: 0 PASS, 1 FAIL.')
            field = columns[1]
            # Materialize once: Spark actions must not reevaluate nondeterministic expressions.
            checked.select(F.col('id').cast('string').alias('id'),
                           F.col('`'+field.replace('`','``')+'`').cast('string').alias('value'),
                           F.col('dq_check')).write.format('delta').mode('overwrite').saveAsTable(stage)
            checked = spark.table(stage)
            invalid = checked.where(F.col('id').isNull() | (F.col('id')=='') | F.col('dq_check').isNull() | ~F.col('dq_check').isin(0,1)).limit(1).count()
            if invalid:
                raise ValueError('Invalid id or dq_check output.')
            totals = checked.agg(F.count('*').alias('checked'),F.sum('dq_check').alias('failed')).first()
            failed = int(totals['failed'] or 0)
            errors = checked.where(F.col('dq_check')==1).select(
                F.lit(run_id).alias('run_id'),F.col('id').cast('string').alias('record_id'),
                F.lit(field).alias('field_name'),F.col('value').alias('field_value'),
                F.lit(payload['error_message']).alias('error_message'))
            errors.write.mode('append').saveAsTable(name(*prefix,'dq_errors'))
            # Count the saved evidence; do not publish a completed run with missing details.
            saved_count = spark.table(name(*prefix,'dq_errors')).where(F.col('run_id')==run_id).count()
            if saved_count != failed:
                raise ValueError('Non-repeatable query output: saved errors do not match the count.')
            spark.createDataFrame([(run_id,int(totals['checked'])-failed,failed,field)], TABLES['dq_results']).write.mode('append').saveAsTable(name(*prefix,'dq_results'))
            spark.sql(f"UPDATE {name(*prefix,'dq_runs')} SET status='completed',completed_at=:ended,source_version=:version WHERE run_id=:rid",
                      args={'ended':datetime.now(timezone.utc).isoformat(),'version':version,'rid':run_id})
        except Exception as error:
            message = str(error)[:4000]
            spark.sql(f"UPDATE {name(*prefix,'dq_runs')} SET status='failed',completed_at=:ended,execution_error=:error WHERE run_id=:rid",
                      args={'ended':datetime.now(timezone.utc).isoformat(),'error':message,'rid':run_id})
            failures.append(payload['rule_key']+': '+message)
        finally:
            spark.sql('DROP TABLE IF EXISTS '+stage)
    if failures:
        raise RuntimeError('\n'.join(failures))
