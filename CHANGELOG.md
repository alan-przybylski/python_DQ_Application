# Changelog

## Unreleased

- Separate Local / SQLite and Databricks workspaces, with environment-filtered
  reports and tickets and explicit data-transfer/snapshot actions.
- Add a native Databricks SQL editor with remote column browsing, fully qualified
  JOINs, bounded asynchronous previews and server-side cancellation. Local copies
  of referenced datasets are not required.
- Store native cloud rules as versioned drafts; publish validated Delta-backed
  definitions through the existing contract 3 job runner. Distinguish draft,
  pending and published states, retaining published snapshots until publication.
- Preserve legacy SQLite rules and mappings through a backed-up additive schema
  migration; keep native SQL out of local execution and local rule-file imports.

- Show runnable local SQL in rule definitions instead of legacy Databricks
  templates. Resolve optional SOURCE placeholders consistently in SQL previews
  and rule forms, saving ordinary SQL and preserving literals/comments.
- Reuse existing local-to-Databricks table mappings when publishing new rules,
  including legacy differently named tables, without changing source keys.

- Preserve Databricks logical date, timestamp, Boolean, integer, string and
  fixed-precision decimal types through local import, schema display and upload.
  Validate CSV values and type edits; store decimals losslessly as text in SQLite.
- Add atomic, backed-up schema alignment that preserves dataset values, technical
  IDs and history; existing DQ anomalies require explicit preservation.

- Daily Databricks notebooks execute checks by default, print execution counts,
  and fail explicitly when no active rules are published. Document explicit job
  parameters so setup-only runs cannot be mistaken for completed DQ checks.
- Result downloads show imported/existing counts, latest remote execution and
  per-run errors; incomplete runs no longer prevent other checks from importing.
- Report history sorts by execution time and identifies each remote check by
  rule description, status and remote run ID. Repeated downloads remain idempotent.

## 0.3.0 — 2026-09-17

### Added

- Databricks SQL connector with browser OAuth, background downloads, preview and
  explicit local SQLite snapshots. Refresh validates the source/schema and backs
  up the local database before atomically replacing rows.
- Named, local Databricks connection profiles: save, switch, update, delete and
  restore the last selection. No stored passwords or tokens.
- Existing-column editor: add, rename, delete, change scalar types and required
  flags, with backups, conversion checks and protection of referenced columns/id.
- Unified rule library with search, table/status filters and current-version KPI.
  Rule details contain Definition, Results and Version history, including SQL diff.
- Permanent deletion in rule details, restricted to active superusers. Removes
  dependent versions/results/errors while preserving other rules in shared runs.
- Windows double-click launchers for the normal workspace and isolated demo.

### Changed

- Quality report is a separate main-menu action.
- Trend charts show active rules only, label endpoints and expose descriptions
  and exact KPI through hover details.
- Login names now require exact spelling and case. Existing accounts/passwords
  are not rewritten.
- CSV templates reflect the current local table schema.
- Expanded PL/EN strings, documentation and regression/UI coverage.

### Removed

- Obsolete MySQL migration script, sample configuration and driver dependency.
  Local SQLite compatibility functions used by existing SQL remain available.

### Verification and limitations

- Regression tests use temporary databases; Windows GUI checks cover 20 views in
  PL/EN at two screen sizes, plus end-to-end workflows and authorization checks.
- Databricks network behavior is tested with fakes. Live account connectivity was
  not independently verified during this release preparation.
- Private databases, profiles, logs and backups are not published. Existing
  exports/backups are not erased by permanent deletion in the application.

## 0.2.0

See [V2 changes](docs/V2_CHANGES.md) for the earlier SQLite workspace, linked DQ
runs, account roles, CSV workflows, localization and synthetic portfolio demo.
