"""Initialize a fresh SQLite installation; optionally create its first admin."""

import argparse
from getpass import getpass

from database.connection import get_connection, initialize_database
from logic.login_functions import create_user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", metavar="USERNAME", help="Create the first account on an empty installation.")
    args = parser.parse_args()
    initialize_database()
    if args.admin:
        connection = get_connection()
        try:
            if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
                raise SystemExit("Accounts already exist. Use the existing admin panel.")
        finally:
            connection.close()
        password = getpass("New admin password: ")
        if not args.admin.strip() or not password or getpass("Repeat password: ") != password:
            raise SystemExit("Username/password is empty or confirmation differs.")
        create_user(args.admin, password, "admin")
        print("First admin created.")
    else:
        print("SQLite schema ready. Existing data was retained.")


if __name__ == "__main__":
    main()
