# DQ Studio
### Make data quality visible.

[![Tests](https://github.com/alan-przybylski/python_DQ_Application/actions/workflows/tests.yml/badge.svg)](https://github.com/alan-przybylski/python_DQ_Application/actions/workflows/tests.yml)
![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/Storage-SQLite-146C72?logo=sqlite&logoColor=white)
![Desktop](https://img.shields.io/badge/Desktop-Tkinter-12243A)

**A local data quality workbench: import CSV, define SQL checks, inspect findings,
and follow quality trends — without configuring a database server.**

Built by **Alan Przybylski** as a Python / SQL / Data Quality portfolio project.
It grew from a course project into a standalone desktop application; this repository
starts with a clean history.

![DQ Studio — actual KPI view with synthetic data](docs/images/results.png)

[Try the demo](#quick-start) · [Walkthrough](docs/DEMO.md) · [Architecture & trade-offs](docs/ARCHITECTURE.md)

## From a messy file to measurable quality

A CSV can import successfully and still contain unusable email addresses, missing
names or out-of-range ages. DQ Studio makes these checks explicit as SQL rules,
records the findings, and shows whether quality improves after corrections.

| Step | What you can do |
|---|---|
| **Import** | Load semicolon-delimited customer CSV files and update matching IDs |
| **Define** | Add, deactivate, archive and revise SQL-based quality rules |
| **Check** | Execute one rule or all active rules for a table |
| **Inspect** | Export row-level findings and review persisted passed/failed counts |
| **Compare** | Visualize historical pass percentages and browse import metadata |
| **Manage** | Create users, change passwords and deactivate accounts |

All application windows share a consistent size and theme. The demo contains
**12 fictional customers, 3 checks and 3 seeded import stages** showing data cleanup.

## Quick start

**Windows desktop · Python 3.14 with Tkinter · [uv](https://docs.astral.sh/uv/)**

```powershell
git clone https://github.com/alan-przybylski/python_DQ_Application.git
cd python_DQ_Application
uv sync --frozen
uv run --frozen python main.py --demo
```

Sign in with **`demo` / `demo-only-2026`**.

Demo mode creates `data/demo.db` on first use and reuses it on later launches.
It never seeds your private `data/app.db`; its CSV exports are also separate.

Open **Rules & quality results → Check DQ** for the initial chart, then try importing
`samples/customers_with_issues.csv`, running all checks, and importing
`samples/customers_clean.csv`. See the [two-minute walkthrough](docs/DEMO.md).

### Application tour

An automatically captured sequence of real application windows, using only synthetic data:

![DQ Studio window walkthrough](docs/images/walkthrough.gif)

### Use your own local data

```powershell
uv run --frozen python -m scripts.init_db --admin admin
uv run --frozen python main.py
```

The setup command prompts for a password and creates the first administrator only
when no users exist. An existing installation keeps its accounts and data.

Without `uv`, create a Python 3.14 virtual environment, install
`requirements.txt`, and run `python main.py`. Demo mode works the same way.

## What this project demonstrates

- **Python + SQL integration:** real CSV imports, SQL rule execution and field-level results.
- **Persistent local storage:** seven SQLite tables, foreign-key checks and migration verification.
- **Desktop development:** coordinated Tkinter windows and embedded Matplotlib charts.
- **Behavior-preserving changes:** regression contracts for existing interfaces, SQL and logic.
- **Reproducibility:** locked dependencies, synthetic samples, isolated demo storage and GitHub Actions.

Read the [architecture notes](docs/ARCHITECTURE.md) for the data model, migration
decisions and intentionally preserved behavior.

## Project structure

```text
main.py           Application entry point; optional isolated demo
ui/               Tkinter views and shared theme
logic/            Import, authentication and KPI/chart functions
database/         SQLite connections and seven-table schema
config/           Project-relative paths and database selection
scripts/          Demo, first-admin setup, migration, screenshot capture
samples/          Synthetic CSV inputs
tests/            Behavioral tests and portable regression contracts
docs/             Architecture, walkthrough and actual screenshots
data/             Local databases and backups — ignored by Git
excels/           Normal-mode CSV exports — ignored by Git
```

## Tests

```powershell
uv run --frozen pytest -q
```

Core tests use temporary databases. Windows desktop checks additionally open all
12 application windows at two screen sizes:

```powershell
$env:DQ_GUI_TESTS = '1'
uv run --frozen pytest -q
```

The CI workflow runs core tests on Windows and Linux, plus GUI tests on Windows.
Linux core tests do not imply full Linux desktop support.

## Storage & honest limitations

Your normal-mode data lives in `data/app.db`. Close the app before copying this file
for a backup or to another computer. Private databases, migration snapshots and
credentials are **not** published in this repository.

This is a local portfolio application, not a production security boundary. SQL rules
must come from trusted authors. The current model preserves historical KPI and
findings but has no shared run ID linking them. Imports may partially commit;
export files are latest-result snapshots rather than a complete file archive.

See [known limitations and next steps](docs/ARCHITECTURE.md#current-limitations)
and [security notes](SECURITY.md). Improving those behaviors is a separate engineering
iteration, not hidden inside the UI refresh.
