# Databricks notebook source
# MAGIC %pip install sqlglot==30.18.0
# COMMAND ----------
# Import this repository as a Git folder. Keep the integrations/ package beside this notebook.
# COMMAND ----------
dbutils.widgets.text('control_catalog', 'workspace')
dbutils.widgets.text('control_schema', 'dq_control')
dbutils.widgets.dropdown('setup_only', 'false', ['true','false'])

# COMMAND ----------
from integrations.databricks_runner import setup, run_job

catalog = dbutils.widgets.get('control_catalog')
schema = dbutils.widgets.get('control_schema')
setup(spark, catalog, schema)
if dbutils.widgets.get('setup_only') == 'false':
    summary = run_job(spark, catalog, schema)
    print('DQ checks completed:', summary)
else:
    print('SETUP ONLY: no checks executed and no results created. Set setup_only=false in the scheduled job parameters.')
