"""Logical dataset types with lossless SQLite storage and explicit validation.

SQLite has no fixed-precision decimal or native date storage. STRING and DECIMAL
use TEXT affinity; dates/timestamps use validated ISO strings. UI and transfer
code see the logical type, including decimal precision and scale.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re

from config.i18n import AppError

TYPES = ('TEXT', 'INTEGER', 'REAL', 'STRING', 'BIGINT', 'INT', 'SMALLINT',
         'TINYINT', 'BOOLEAN', 'DATE', 'TIMESTAMP', 'TIMESTAMP_NTZ', 'DECIMAL(10,2)',
         'DECIMAL(8,3)', 'DECIMAL(38,18)')
INTEGER_BITS = {'INTEGER':64, 'BIGINT':64, 'INT':32, 'SMALLINT':16, 'TINYINT':8}


def decimal_spec(kind):
    match = re.fullmatch(r'DECIMAL\((\d+),(\d+)\)', kind)
    if match:
        precision, scale = map(int, match.groups())
        if 1 <= precision <= 38 and 0 <= scale <= precision:
            return precision, scale
    return None


def supported(kind):
    return kind in TYPES or decimal_spec(kind) is not None


def storage_type(kind):
    if not supported(kind):
        raise AppError('Unsupported dataset type: {kind}', kind=kind)
    if kind == 'STRING' or decimal_spec(kind):
        # Quoted type name deliberately includes TEXT to prevent SQLite numeric
        # affinity from rounding decimals or stripping zeros from string IDs.
        return '"' + kind + ' TEXT"'
    return kind


def logical_type(declaration):
    declaration = declaration.upper()
    if declaration.endswith(' TEXT') and (declaration[:-5] == 'STRING' or decimal_spec(declaration[:-5])):
        return declaration[:-5]
    return declaration


def typed_value(value, kind):
    if value is None:
        return None
    try:
        if kind == 'DATE':
            if isinstance(value, datetime):
                raise ValueError
            text = value.isoformat() if isinstance(value, date) else value
            if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
                raise ValueError
            date.fromisoformat(text)
            return text
        if kind in ('TIMESTAMP', 'TIMESTAMP_NTZ'):
            text = value.isoformat() if isinstance(value, datetime) else value
            if not isinstance(text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?', text):
                raise ValueError
            parsed = datetime.fromisoformat(text)
            if kind == 'TIMESTAMP_NTZ' and parsed.tzinfo is not None:
                raise ValueError
            return text
        if kind == 'BOOLEAN':
            if type(value) in (bool, int) and value in (0, 1):
                return int(value)
            if isinstance(value, str) and value.lower() in ('true', 'false', '0', '1'):
                return int(value.lower() in ('true', '1'))
            raise ValueError
        spec = decimal_spec(kind)
        if spec:
            if isinstance(value, (float, bool, bytes)):
                raise ValueError
            text = str(value)
            if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
                raise ValueError
            number = Decimal(text)
            precision, scale = spec
            with localcontext() as context:
                context.prec = 80
                if not number.is_finite() or abs(number) >= Decimal(10) ** (precision-scale):
                    raise ValueError
                if number != number.quantize(Decimal(1).scaleb(-scale)):
                    raise ValueError
            return text
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        raise AppError('Value does not fit {kind}. No data was saved.', kind=kind) from None
    raise AppError('Unsupported dataset type: {kind}', kind=kind)


def remote_value(value, kind):
    if value is None:
        return None
    if kind == 'DATE':
        return date.fromisoformat(typed_value(value, kind))
    if kind in ('TIMESTAMP', 'TIMESTAMP_NTZ'):
        return datetime.fromisoformat(typed_value(value, kind))
    if kind == 'BOOLEAN':
        return bool(typed_value(value, kind))
    if decimal_spec(kind):
        return Decimal(typed_value(value, kind))
    return value
