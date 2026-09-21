"""Build a standalone notebook for manual upload; no local configuration is embedded."""

from pathlib import Path


def build(destination):
    root=Path(__file__).resolve().parents[1]
    contract=(root/'integrations/databricks_contract.py').read_text(encoding='utf-8')
    runner=(root/'integrations/databricks_runner.py').read_text(encoding='utf-8')
    runner='\n'.join(line for line in runner.splitlines() if not line.startswith('from integrations.databricks_contract import'))
    entry=(root/'databricks_dq_job.py').read_text(encoding='utf-8')
    entry='\n'.join(line for line in entry.splitlines() if not line.startswith('from integrations.databricks_runner import'))
    result='# Databricks notebook source\n'+contract+'\n# COMMAND ----------\n'+runner+'\n# COMMAND ----------\n'+entry+'\n'
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(result,encoding='utf-8')
    return destination


if __name__=='__main__':
    print(build(Path(__file__).resolve().parents[1]/'artifacts/DQ_daily_checks.py'))
