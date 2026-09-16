# Security & data handling

DQ Studio is a trusted local desktop portfolio application, not a network service
or security boundary around the SQLite file.

- Account passwords are bcrypt hashes. New/changed passwords require six
  characters, an uppercase letter and a digit; bcrypt's 72-byte UTF-8 maximum is
  checked explicitly. Existing password hashes are never reset by migrations.
- Only active superusers administer users; the last active superuser is protected
  from demotion/deactivation. Filesystem access can bypass all application roles.
- Rule execution is read-only, restricted to dataset tables, output-validated and
  time-limited. This is not an operating-system sandbox; use trusted SQL authors.
- CSV exports protect spreadsheet formula prefixes by default. Raw export is an
  explicit option. Review exported files before opening them in spreadsheets.
- Private databases, backups, preferences and migration snapshots are Git-ignored.
  Exports saved outside the project are your responsibility. Do not force-add
  private files or store exports under tracked source/documentation folders.
- Public demo credentials are intentional and belong only to the synthetic demo.
  Public samples use fictional identities and example.test email addresses.
- A clean Git history does not revoke credentials published elsewhere. Rotate
  exposed credentials. Keep local database backups private as well.

For sensitive reports, use GitHub private vulnerability reporting if available,
or contact the owner privately. Do not post credentials or private data in issues.
