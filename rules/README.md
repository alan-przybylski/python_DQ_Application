# Rules as code

Each rule consists of a `.rule.toml` metadata file and a neighboring `.sql` file.
Both belong in Git. `dq_check = 0` means PASS; `1` means FAIL.

Keep `key` unchanged when editing a rule: it is its identity across databases.
The key is not a database ID. Imports of identical content do nothing; changed
content archives the previous definition and increments its database version.
Changing the target table requires a new key. Missing files never delete rules.
Use `active = false` to deactivate one explicitly. Severity is low, medium or high.

The two supplied examples are opt-in; they are not installed on app startup.
Importing them creates separate rules, even if a legacy rule has a similar name.
To version your existing rules instead, export them first and retain their keys.

Use **Import rule files** and **Export rule files** in the rule library.
Import and export require a signed-in superuser.
Validation uses the selected local database's schema and data, without running
checks or creating tickets. The entire import rolls back if any definition fails.

Export includes active and inactive definitions, not database rows or passwords.
It refuses to overwrite edited files. Use an empty directory for a new export,
then compare changes with Git before replacing your tracked definitions.
