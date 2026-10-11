# Desktop application

[Live web demo](https://alan-dq-studio.streamlit.app/) · [Project overview](../README.md)

## Start a workspace

Windows desktop requires Python 3.14 with Tkinter. From the cloned repository:

```powershell
uv sync --frozen
uv run --frozen python main.py --demo
```

A fresh desktop demo uses `demo` / `Demo2026`, 12 fictional customers, three rules
and three seeded runs. Existing demo databases and passwords are reused. This
desktop seed is separate from the web demo's two datasets and eight rules.

To use your own data, run `uv run --frozen python main.py`. On first launch,
create your administrator account. Normal storage is `data/app.db`; the desktop
demo uses `data/demo.db`. Both are Git-ignored.

After setup, double-click **Start DQ Studio.cmd** or **Start DQ Studio Demo.cmd**.
The launchers use the project's `.venv`; leave them inside the repository.
Startup diagnostics are written to `data/launcher.log`.

## Navigation

The main menu contains Local, Databricks, Rule library, Quality report, DQ tickets,
Settings and Manage users for administrators. PL/EN can be selected at sign-in.

- **Local:** datasets, SQL, check execution, reports and CSV import/export.
- **Databricks:** profile selection, cloud tables, native SQL, runs and transfers.
- **Rule library:** one inventory with All / Local / Databricks and profile filters.
- **Quality report:** per-run evidence and historical trends, filtered by environment.
- **Settings:** language and connection profiles.

## Local data and SQL

Open Local's import/export menu to create or refresh datasets from CSV. Preview
the mapping before importing; source rows and the import log commit together.
Table editing supports guarded type conversion and creates a database backup.

The SQL editor browses local tables and columns. Ctrl+Enter runs the selection
or the whole editor. Preview is read-only, limited to 500 rows and a best-effort
10-second execution timeout. Use ordinary table names and JOINs; `{{SOURCE}}`
is an optional placeholder for the selected table.

Save a rule returning `id`, the tested field as its second column and `dq_check`:
**0 = PASS, 1 = FAIL**. Each execution stores a separate run and result details.
SQL errors are execution failures, not fabricated data-quality results.

## Databricks workspace

Choose a saved profile, catalog and schema, then Browse cloud tables. Native
Databricks SQL can join remote tables directly, without importing them into SQLite.

```sql
SELECT p.product_id AS id,
       p.country_code,
       CASE WHEN c.country_code IS NULL THEN 1 ELSE 0 END AS dq_check
FROM workspace.dq_app.products AS p
LEFT JOIN workspace.dq_app.ref_countries AS c
    ON p.country_code = c.country_code;
```

Cloud SQL preview returns up to 500 rows and requests cancellation after 60
seconds of query execution. Connection/OAuth time is separate. Scheduled checks
evaluate the datasets without the preview row limit.

**Save as new cloud rule** creates a local draft. **Save cloud changes** versions
the selected draft. **Publish saved rule** validates and publishes its saved
definition; the list shows Draft, Pending publication or Published. Native cloud
rules require Delta dependencies with readable snapshot history.

**Manage schedules in Databricks** opens the workspace's Jobs page. A configured
job executes published rules from the selected control catalog/schema.
Cloud history is stored in `dq_control.dq_runs`, `dq_results` and `dq_errors`.
**Download all results** imports the profile's available check history, skips
duplicates and keeps results usable without a local source-table copy.

Transfers are explicit: send a local table, create a local snapshot, export a
cloud preview or download results. Connection profiles store non-secret settings;
they do not store passwords or tokens.

See [connection setup](DATABRICKS.md), [job setup and synchronization](DATABRICKS_SYNC.md)
and [cross-table SQL](CROSS_TABLE.md).

## Rules, tickets and accounts

Local rule edits require deactivation and create a new version. Native cloud
drafts have their own save/publish lifecycle. Legacy local rules already linked
to Databricks remain visible as linked local definitions.

Rules can also be imported/exported as TOML metadata and separate SQL files.
Stable keys avoid duplicate imports. See the [rule examples](../rules/README.md).

A failed check creates one open DQ ticket per rule and dataset. Low / Medium /
High severity sets a 7 / 3 / 1 calendar-day deadline. Tickets keep ownership,
comments, activity and a link to failure evidence. A subsequent successful,
nonempty check closes the ticket. Empty or failed executions do not close it.

Manage users supports account creation, deactivation and role changes. New or
changed passwords need six characters, an uppercase letter and a digit. Passwords
are hashed with bcrypt. The last active superuser cannot be removed or demoted.

Permanent rule deletion removes its result history and cancels related open
tickets; deactivate a rule when you want to retain its history instead.

## Storage and limitations

Close the application before copying a database for backup. Existing databases
receive backups before applicable schema upgrades. Dataset edits and CSV exports
do not automatically archive complete source datasets.

Desktop roles protect application operations, not direct access to the SQLite
file. Large local imports and checks can block the UI. See [architecture and
limitations](ARCHITECTURE.md#current-limitations) and [security notes](../SECURITY.md).
