"""Reference deterministic normalizers. Locale assumptions are explicit."""

from datetime import date
from decimal import Decimal, InvalidOperation
import re

from edi_reference.domain.normalization import NormalizationError


class IdIdrMoneyNormalizer:
    normalizer_id = "money.id-ID.IDR"
    version = "1"
    value_type = "money"

    def normalize(self, raw_value: str) -> dict[str, str]:
        value = raw_value.strip()
        value = re.sub(r"(?i)^rp\.?\s*", "", value).replace(" ", "")
        if not re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:,\d+)?", value):
            raise NormalizationError("INVALID_MONEY_FORMAT")
        canonical = value.replace(".", "").replace(",", ".")
        try:
            amount = Decimal(canonical)
        except InvalidOperation:
            raise NormalizationError("INVALID_MONEY_FORMAT") from None
        return {"amount": format(amount, "f"), "currency": "IDR"}


class IsoDateNormalizer:
    normalizer_id = "date.iso-8601"
    version = "1"
    value_type = "date"

    def normalize(self, raw_value: str) -> str:
        value = raw_value.strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise NormalizationError("INVALID_DATE_FORMAT")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise NormalizationError("INVALID_DATE_FORMAT") from None


class TrimmedIdentifierNormalizer:
    normalizer_id = "identifier.trimmed"
    version = "1"
    value_type = "identifier"

    def normalize(self, raw_value: str) -> str:
        value = raw_value.strip()
        if not value:
            raise NormalizationError("EMPTY_IDENTIFIER")
        return value
