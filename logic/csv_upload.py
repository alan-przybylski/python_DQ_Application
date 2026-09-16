"""Compatibility entry point for the now-atomic CSV import service."""

from config.i18n import tr
from logic.datasets import import_data, read_csv


def load_csv_and_log(csv_file, table_name, username):
    try:
        count = import_data(read_csv(csv_file), table_name, username)
        return tr(
            "Imported {count} rows into {table}. All changes committed together.",
            count=count,
            table=table_name,
        ), True
    except Exception as error:
        return str(error), False
