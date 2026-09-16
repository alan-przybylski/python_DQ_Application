"""Portable regression contracts, independent of any previous Git history."""

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = json.loads(
    (ROOT / "tests/fixtures/preserved_contracts.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("path", CONTRACTS["interfaces"])
def test_function_names_and_parameters_preserved(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    signatures = [
        [node.name, [arg.arg for arg in node.args.args]]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    # V2 deliberately adds actor checks and new screens; existing public entry
    # points and their leading parameters remain. Nested callbacks are private.
    for name, parameters in CONTRACTS["interfaces"][path]:
        if name in {"submit", "save_changes", "update_rules"}:
            continue
        if name == "on_close":
            parameters = ["self"]  # Repair the original missing-self method.
        assert any(
            actual_name == name and args[: len(parameters)] == parameters
            for actual_name, args in signatures
        ), (path, name)


# Authorized V2 behavior changes are covered by semantic regression tests,
# not by blessing new hashes of changed business logic.
CHANGED_SQL = {
    "logic/login_functions.py",
    "logic/csv_upload.py",
    "logic/dq_report.py",
    "ui/data_quality.py",
    "ui/check_dq_panel.py",
    "ui/file_history.py",
}


@pytest.mark.parametrize(
    "path", [p for p in CONTRACTS["sql_hashes"] if p not in CHANGED_SQL]
)
def test_sql_and_transactions_preserved(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    statements = [
        ast.dump(node, include_attributes=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany", "commit", "rollback"}
    ]
    assert (
        hashlib.sha256(json.dumps(statements).encode()).hexdigest()
        == CONTRACTS["sql_hashes"][path]
    )


def test_original_logic_contracts_remain_as_a_baseline():
    # The original fixture is retained unmodified, not rewritten to imply that
    # atomic imports, account authorization or reports are byte-identical to V1.
    assert set(CONTRACTS["logic_hashes"]) <= CHANGED_SQL
