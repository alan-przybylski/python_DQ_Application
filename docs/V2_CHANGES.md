# V2 — approved behavior changes

This release implements the owner's explicit approval for password requirements,
superuser/user role assignment, PL/EN, interactive reports, CSV exports, custom
datasets, atomic imports and a DQ run identifier.

- Password policy affects creation/change only. Legacy admin login and hashes
  are preserved. Old role admin is normalized to superuser.
- Existing function entry points remain. Administrative service functions now
  take an optional actor argument; unprivileged calls are rejected.
- Import now commits the entire file and history together, replacing partial-row
  commits. Duplicate CSV IDs are rejected. Matching database IDs still update.
- Dataset tables are discovered dynamically; internal tables are excluded from
  import/export and rule selection. Schema editing/deletion of existing tables
  is not part of this release.
- dq_runs and nullable run_id columns link new KPI and details. Historical rows
  remain intact and unlinked; run IDs are not guessed from timestamps.
- Rule evaluation is SELECT-only against dataset tables and validates the
  id / tested field / dq_check output contract. Malformed legacy rules produce
  an explicit execution error rather than misleading result counts.
- CSV export is explicit with a chosen destination, replacing automatic
  latest-result filenames/file opening. Report exports contain failed checks;
  complete pass/fail detail remains in SQLite.
- PL/EN translates application-owned interface text. User data, SQL, stored
  descriptions, role/type identifiers and low-level database errors are retained.
- All windows use the shared sizing helper. Query execution remains synchronous;
  background processing is intentionally not introduced.

## Upgrade and recovery

Back up/close any running application before upgrading. Initialization makes an
additional pre-migration SQLite backup in data/backups/ for an established DB.
The migration adds columns/table and maps roles; it does not replace databases,
remove rows or reset passwords. Original MySQL data and the old repository are
not modified.

To recover an older version, close the application, preserve the current database
under a different name, restore the pre-migration backup, and use the matching
older code version. Restoring a backup without preserving the current DB would
discard subsequent local work.

## Verification

The suite tests unchanged historical rows and hashes, weak legacy login,
idempotent migrations, backup integrity, atomic imports, actor checks, distinct
run results, rule validation, PL/EN and actual Tkinter workflows. Public
screenshots are regenerated solely from a temporary synthetic database.
