"""Explicit Indonesian workspace normalization, not tax/compliance validation."""

import re
from datetime import date

from edi_reference.adapters.normalizers import IdIdrMoneyNormalizer, IsoDateNormalizer


def normalize_field(name: str, raw: str) -> object:
    value = raw.strip()
    if name == "total_idr":
        return IdIdrMoneyNormalizer().normalize(value)
    if name == "npwp":
        if not re.fullmatch(r"(?:[0-9]{15,16}|[0-9]{2}\.[0-9]{3}\.[0-9]{3}\.[0-9]-[0-9]{3}\.[0-9]{3})", value):
            raise ValueError("INVALID_NPWP_FORMAT")
        return re.sub(r"[.\-]", "", value)
    if name == "document_date":
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return IsoDateNormalizer().normalize(value)
        match = re.fullmatch(r"([0-9]{1,2})([/\-])([0-9]{1,2})\2([0-9]{4})", value)
        if not match:
            raise ValueError("INVALID_DATE_FORMAT")
        day, _, month, year = match.groups()
        return date(int(year), int(month), int(day)).isoformat()
    if name != "document_number" or not value or len(value) > 200:
        raise ValueError("INVALID_FIELD")
    return value
