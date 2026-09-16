# Security & data handling

This desktop portfolio is intended for trusted local use. Do not expose it as a
multi-user service or run SQL supplied by an untrusted party.

- Private databases, migration snapshots, configuration credentials and generated
  exports are excluded from Git.
- Public samples use fictional names and `example.test` email addresses.
- The demo account is public by design and is created only in a separate demo DB.
- Bcrypt protects stored password hashes, not access to the SQLite file itself.
- Creating a private copy or a clean Git history does **not** revoke credentials
  previously published elsewhere. Previously exposed credentials should be rotated.

For a sensitive report, use GitHub's private vulnerability reporting if enabled;
otherwise contact the repository owner privately. Do not place credentials, private
data or exploit details in a public issue.

See [GitHub's guidance on removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
for the limitations of history rewriting and previously created copies.
