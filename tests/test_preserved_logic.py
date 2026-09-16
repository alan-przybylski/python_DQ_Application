"""Portable regression contracts, independent of any previous Git history."""

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = json.loads((ROOT / "tests/fixtures/preserved_contracts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CONTRACTS["interfaces"])
def test_function_names_and_parameters_preserved(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    signatures = [[node.name, [arg.arg for arg in node.args.args]]
                  for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert signatures == CONTRACTS["interfaces"][path]


@pytest.mark.parametrize("path", CONTRACTS["sql_hashes"])
def test_sql_and_transactions_preserved(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    statements = [ast.dump(node, include_attributes=False) for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                  and node.func.attr in {"execute", "executemany", "commit", "rollback"}]
    assert hashlib.sha256(json.dumps(statements).encode()).hexdigest() == CONTRACTS["sql_hashes"][path]


@pytest.mark.parametrize("path", CONTRACTS["logic_hashes"])
def test_business_logic_unchanged(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    assert hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest() == CONTRACTS["logic_hashes"][path]
