"""Resolve optional legacy SOURCE placeholders without touching SQL literals."""
import re

from config.i18n import AppError
from logic.datasets import quote


_TOKENS = re.compile(
    r"'(''|[^'])*'|\"(\"\"|[^\"])*\"|`(``|[^`])*`|\[[^\]]*\]|--[^\n]*|/\*[\s\S]*?\*/|\{\{\s*source\s*\}\}",
    re.I,
)


def bind_source(sql, table=None):
    def replace(match):
        if not match[0].startswith('{{'):
            return match[0]
        if not table:
            raise AppError('Select a table for the SOURCE placeholder, or use its actual name in FROM.')
        return quote(table)
    return _TOKENS.sub(replace,sql)
