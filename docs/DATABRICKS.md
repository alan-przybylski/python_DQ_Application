# Databricks snapshots and safe table editing

## Connect a test account

1. Update dependencies from the project folder: `uv sync --frozen`.
2. In Databricks, select a SQL warehouse and open **Connection details**.
   Copy **Server hostname** (without `https://`) and **HTTP path**.
3. Give the account access to that warehouse and permission to use the catalog
   and schema and select the source table/view. Use a read-only account/grant
   where possible. This connector issues SELECT only; it never writes remotely.
4. In DQ Studio, open **01 Import CSV → Import from Databricks**. Enter the two
   connection values plus catalog, schema and table/view in separate fields.
5. Choose **Sign in and download preview**, then complete OAuth in the browser.
   DQ Studio stores no password, PAT or OAuth-token file. No credentials belong
   in Git, CSV, screenshots or messages. Connection settings can be saved in a
   named local profile (see below); browser sign-in may still be required.
6. Inspect the first 20 rows and the source → local column mapping in the headers.
   Enter a new local name, e.g. `db_customers`, then **Save locally** and confirm.
7. Return to the main menu: **Rule library → Add rule** can select the new table.
   **Quality report** is now a separate main-menu button; run the local checks there.

The browser OAuth implementation follows the official
[Databricks SQL Connector documentation](https://docs.databricks.com/aws/en/dev-tools/python-sql-connector).
The locked Python connector is installed with the normal application dependencies;
ODBC/JDBC and a local Databricks server are not required.

## Connection profiles

Enter a name in **Connection profile**, fill the connection fields, then choose
**Save profile**. The source table is optional in a saved profile; fill it before
downloading. Pick an existing name from the dropdown to switch connections.
Changes to an existing profile require **Save profile** and overwrite confirmation;
typing a different name creates another profile. **Delete profile** asks for
confirmation and does not remove imported datasets or DQ history.

The last saved/selected profile is restored when the window or application reopens.
Profiles store only hostname, HTTP path, catalog, schema and table—not passwords,
tokens, row data or an OAuth session. Switching profiles clears any downloaded
preview so data cannot be saved under misleading connection settings. Profile
controls are disabled while a network download is running.

Settings live beside the selected database, e.g. `data/app.databricks-profiles.json`
or `data/demo.databricks-profiles.json`. They are shared by users of that local
workspace, not an account-security boundary; `data/` is excluded from Git.
Writes use atomic file replacement. A damaged/unrecognized file is reported and
never silently overwritten. Saved settings do not remove OAuth sign-in requirements.

## Small test source (run manually in your own Databricks SQL editor)

Select a catalog/schema where your account can create tables, then run:

```sql
CREATE TABLE dq_customers_test AS
SELECT * FROM VALUES
  (1, 'Alice Example', 'alice@example.test', 28, 'PL', 'Warsaw'),
  (2, 'Bob Example', 'not-an-email', 17, 'PL', 'Gdansk'),
  (3, '', 'carol@example.test', 35, 'DE', 'Berlin'),
  (4, 'David Example', NULL, 145, 'FR', 'Paris'),
  (4, 'Duplicate Key', 'duplicate@example.test', 42, 'PL', 'Krakow')
AS t(id, name, email, age, country_code, city);
```

This creates a new table; it does not replace an existing table of the same name.
The deliberately bad values and duplicate key are useful for testing DQ.
After importing as `db_customers`, one local SQLite rule is:

```sql
SELECT id, age,
       CASE WHEN age BETWEEN 18 AND 120 THEN 0 ELSE 1 END AS dq_check
FROM db_customers;
```

Expected outcome for this rule: 3 passed, 2 failed, 60% KPI.
Downloading/importing does not automatically execute rules.

## Local snapshot semantics

- The source remains remote and unchanged. All existing DQ execution stays on SQLite.
- `id` is generated locally for every snapshot. A source `id` becomes `source_id`;
  duplicates and NULL source keys remain intact. Punctuation in other column names
  is replaced with underscores; conflicting names receive suffixes. Inspect the
  mapping before saving. Source `id` is not assumed to be a unique business key.
- Local IDs are positions within one snapshot, not stable source identifiers.
  Row ordering and local IDs may change on refresh. Use the preserved source key
  for business comparisons; use run ID to interpret historical findings.
- Refresh replaces all rows (including replacing with zero rows, if confirmed).
  It is not an append, merge, CDC pipeline or scheduled sync. Only tables whose
  last import log matches this exact source can be refreshed. Column names/types,
  key structure and required flags must still match the generated local schema.
  Changed source/local schemas require a new local table rather than automatic DDL.
- Refresh creates a full SQLite backup in `data/backups/` before deleting rows.
  Replacement and import-log entry commit together or roll back together.
  Rule definitions, archived versions, runs, KPI and findings are not rewritten.
- Import history contains a `databricks://host/catalog/schema/table` source reference.
  No connection secrets are included. Sources/warehouse permissions can change;
  the application does not promise a permanent remote snapshot/version ID.

## Supported data and bounds

| Databricks type | Type shown in the app | SQLite storage |
|---|---|---|
| Boolean | BOOLEAN | Integer 0/1 |
| Tiny/small/int/bigint | TINYINT / SMALLINT / INT / BIGINT | Integer; local technical `id` remains INTEGER |
| Float/double | REAL | Real; non-finite values rejected |
| String | STRING | Text affinity; leading zeros preserved |
| Char/varchar | TEXT | Text; empty string remains distinct from NULL |
| Decimal(p,s) | DECIMAL(p,s) | Exact text, without floating-point rounding |
| Date/timestamp/timestamp_ntz | DATE / TIMESTAMP / TIMESTAMP_NTZ | Validated ISO text; preserves the connector's datetime/offset |
| NULL | TEXT fallback | NULL |

STRING and DECIMAL use quoted storage declarations such as `"STRING TEXT"`
and `"DECIMAL(10,2) TEXT"` to prevent SQLite numeric affinity from changing values.
The app displays the logical type and restores it on upload. A driver that omits
decimal precision/scale falls back to exact TEXT storage. SQLite still uses its
own SQL semantics; these declarations do not implement Databricks arithmetic.

Complex types (array/map/struct/variant), binary and other unsupported types are
rejected, not silently stringified. Expose a source view that explicitly casts or
selects the desired scalar fields. Decimal text is exact storage; if a local DQ
rule casts it to REAL, that calculation has SQLite floating-point limitations.

Default limit: 10,000 rows, configurable up to 100,000. The query requests one
extra row to detect overflow and rejects the entire download if the limit is
exceeded. An approximate 50 MiB in-memory budget includes payload and per-value
overhead; this is a guard, not a hard process-memory limit. No partial dataset is
saved as a complete one. There is no automatic retry of a local save.

Downloads run off the Tk thread. Cancel discards the download; a currently blocking
network/OAuth operation may finish later. Closing the window is safe: the worker
cannot write SQLite or update destroyed widgets. Local saving and backups still
run on the UI thread and can briefly block it.

## Edit existing columns

Open **01 Import CSV → Edit table columns**, select a table and a column. You can
add, rename, delete, change TEXT/INTEGER/REAL and toggle Required. Confirm each
operation; successful operations show the backup path. New CSV templates and rule
column selectors use the current schema immediately (download a new template;
previously exported files are not rewritten).

Safeguards:

- Technical `id` and primary keys cannot be changed. Accounts/history/internal
  tables are excluded entirely.
- Current ACTIVE and INACTIVE rule SQL is analyzed by SQLite without executing it.
  Column dependencies include aliases and joins, not only the rule's target table.
  Edit the rule first if it uses an affected column. Invalid current SQL blocks
  destructive/type changes; wildcard/expression rules may also block additions.
  Archived historical versions stay unchanged and are not runnable definitions.
- Values must all convert safely. Leading-zero text, empty text, overflow,
  fractional-to-integer truncation, non-finite numbers and precision loss are
  rejected. NULL is retained unless Required is requested, in which case existing
  NULL rows must be filled first. A new Required column is possible only on an
  empty table; add it nullable, fill values, then make it Required otherwise.
- Collations, primary keys and the auto-increment high-water mark are preserved.
  Advanced unmanaged schemas with indexes, views, triggers, foreign keys, custom
  defaults/checks or generated columns require a reviewed migration and are
  conservatively rejected. The editor never silently drops those objects.
- Full backups, transactional DDL and rollback protect rows and schema. Existing
  reports remain historical evidence; editing does not recalculate old KPI.
- Changing a Databricks snapshot's columns can intentionally make it ineligible
  for refresh. Import a fresh table if source and local schema no longer agree.

To restore a backup, close DQ Studio and replace the intended database with the
shown backup file, retaining a copy of the current file first. A full database
restore also restores accounts and all history to that backup's point in time.

## Verification boundary

Automated tests cover read-only SQL construction, identifier quoting, type mapping,
duplicate keys, NULL/empty preservation, bounds, cancellation, transactional refresh,
backups, unchanged history, column protections, conversion rollback and PL/EN UI.
They use fake Databricks connections and isolated temporary SQLite databases.
Real warehouse connectivity, OAuth grants and Free Edition availability must be
checked with the user's account; no live account was used during implementation.
