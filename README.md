# DQ Studio

### Make data quality visible.

[![Tests](https://github.com/alan-przybylski/python_DQ_Application/actions/workflows/tests.yml/badge.svg)](https://github.com/alan-przybylski/python_DQ_Application/actions/workflows/tests.yml)
![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/Storage-SQLite-146C72?logo=sqlite&logoColor=white)
![Desktop](https://img.shields.io/badge/Desktop-Tkinter-12243A)

**Turn CSV files into traceable data quality checks — without a database server.**

A local Python / SQL / Data Quality portfolio project by **Alan Przybylski**.
Import a dataset, define SQL rules, run checks, and investigate failed records
alongside historical quality trends. This standalone repository starts with a
clean history, separate from the original course project.

![Actual report: KPI cards, quality trend and failed records](docs/images/results.png)

[Try the demo](#quick-start) · [Walkthrough](docs/DEMO.md) · [Architecture](docs/ARCHITECTURE.md) · [V2 changes](docs/V2_CHANGES.md)

## One workspace, from import to investigation

| Step | What you can do |
|---|---|
| Import | Choose an existing table and its CSV template, or create a new table from CSV/manual columns |
| Prepare | Preview data, map columns, choose types and required fields; import all rows or none |
| Define | Add SQL rules for any dataset, archive versions and revise inactive rules |
| Run | Execute one rule or all active rules; each execution gets its own persistent run ID |
| Investigate | View KPI cards, trends and searchable failed records for the selected run |
| Export | Save an entire dataset or the selected run's errors to a chosen CSV file |
| Manage | Assign superuser/user roles, change passwords and deactivate accounts |
| Localize | Switch PL/EN at sign-in; the preference is remembered locally |

Consistent window sizes, scrollable tables and a shared navy/teal theme.
The demo includes **12 fictional customers, 3 SQL checks and 3 linked runs**
showing a data cleanup journey.

## Quick start

**Windows desktop · Python 3.14 with Tkinter · [uv](https://docs.astral.sh/uv/)**

```powershell
git clone https://github.com/alan-przybylski/python_DQ_Application.git
cd python_DQ_Application
uv sync --frozen
uv run --frozen python main.py --demo
```

A **fresh** demo uses **`demo` / `Demo2026`**.
Existing demo databases are reused, never reset; their passwords remain unchanged.
Demo data lives in `data/demo.db`, separate from your private `data/app.db`.

Open **Rules & quality results → Quality report**. Import
`samples/customers_with_issues.csv`, run all customer checks, inspect the failed
records, then repeat with `samples/customers_clean.csv`.

### Application tour

Real application windows, captured using temporary synthetic data only:

![DQ Studio walkthrough](docs/images/walkthrough.gif)

### Use your own data

```powershell
uv run --frozen python -m scripts.init_db --admin your_login
uv run --frozen python main.py
```

The setup command creates the first **superuser** only on an empty installation.
Passwords need **6 characters, an uppercase letter and a digit**. Existing users
and passwords are retained. The account form explains unmet requirements.

Without uv, create a Python 3.14 virtual environment, install
`requirements.txt`, then run `python main.py`.

## Engineering highlights

- **Atomic writes:** CSV rows, optional new table and import log commit together.
- **Traceable results:** a DQ run links user, time, table, KPI and field-level findings.
- **Guarded SQL:** read-only dataset access, output validation and a per-rule execution timeout.
- **Safe upgrades:** additive SQLite migrations, automatic backup, no invented links for legacy history.
- **Explicit permissions:** account changes are checked in the service layer, not only hidden in the UI.
- **Reproducible demo:** locked dependencies, synthetic samples and automated Windows/Linux tests.

## Project structure

```text
main.py           Entry point; optional isolated demo
ui/               Tkinter screens, shared widgets and theme
logic/            Accounts, datasets, rule execution, history and exports
database/         SQLite connections, original schema, additive migrations
config/           Paths, database selection and PL/EN translations
scripts/          Demo, first-user setup, MySQL import, screenshot capture
samples/          Fictional CSV inputs
tests/            Behavioral regression tests and actual Tkinter workflows
docs/             Walkthrough, architecture and actual screenshots
data/             Private databases, preferences and backups (Git-ignored)
excels/           Legacy export location (Git-ignored generated files)
```

## Tests

```powershell
uv run --frozen pytest -q
# On a Windows desktop:
$env:DQ_GUI_TESTS = '1'
uv run --frozen pytest -q
```

Tests use temporary databases, never private application data. GUI checks cover
15 views in PL/EN at two screen sizes and an import → rule → report → export flow.
CI runs core tests on Windows and Linux, plus GUI tests on Windows.

## Storage and limitations

Your private data stays in `data/app.db`; close the app before copying the database
for a backup. The V2 upgrade also creates a pre-migration backup automatically.
CSV exports are explicit snapshots saved where you choose.

Old KPI and findings are preserved; only new executions have linked run history.
This is a local portfolio app, not a production multi-user security boundary:
anyone who can access the SQLite file can bypass application roles. Large imports
and checks still run on the UI thread.

Read the [architecture and limitations](docs/ARCHITECTURE.md#current-limitations)
and [security notes](SECURITY.md) before using sensitive data.
