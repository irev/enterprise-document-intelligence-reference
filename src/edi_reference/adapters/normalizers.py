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


# Month names are matched case-insensitively. Only full names and the common
# three-letter abbreviations are accepted; anything else is rejected.
_MONTHS = {
    "januari": 1, "january": 1, "jan": 1,
    "februari": 2, "february": 2, "feb": 2, "pebruari": 2,
    "maret": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6,
    "juli": 7, "july": 7, "jul": 7,
    "agustus": 8, "august": 8, "agu": 8, "agt": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nopember": 11, "nov": 11,
    "desember": 12, "december": 12, "des": 12, "dec": 12,
}


def _calendar(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise NormalizationError("INVALID_CALENDAR_DATE") from None


class TextualDateNormalizer:
    """`15 Juli 2026`, `15 Jul 2026`, `20 September 2026`, `September 20, 2026`, `Sep 20 2026`.

    The month is named, so day/month order is unambiguous. Weekday prefixes and
    any other text are rejected rather than skipped.
    """

    normalizer_id = "date.textual.id-en"
    version = "1"
    value_type = "date"
    # Separators between digits and letters are optional (OCR often drops the space);
    # the digit/letter boundary keeps the reading unambiguous.
    _DAY_FIRST = re.compile(r"(\d{1,2})[\s-]*([A-Za-z]{3,9})\.?[\s-]*(\d{4})")
    _MONTH_FIRST = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})")

    def normalize(self, raw_value: str) -> str:
        value = " ".join(raw_value.split())
        match = self._DAY_FIRST.fullmatch(value)
        if match:
            day, name, year = match.groups()
        else:
            match = self._MONTH_FIRST.fullmatch(value)
            if match is None:
                raise NormalizationError("INVALID_DATE_FORMAT")
            name, day, year = match.groups()
        month = _MONTHS.get(name.lower())
        if month is None:
            raise NormalizationError("UNKNOWN_MONTH_NAME")
        return _calendar(int(year), month, int(day))


class _NumericDate:
    value_type = "date"
    _PATTERN = re.compile(r"(\d{1,2})([/.-])(\d{1,2})\2(\d{4})")

    def _parts(self, raw_value: str) -> tuple[int, int, int]:
        match = self._PATTERN.fullmatch(raw_value.strip())
        if match is None:
            raise NormalizationError("INVALID_DATE_FORMAT")
        return int(match.group(1)), int(match.group(3)), int(match.group(4))


class UnambiguousNumericDateNormalizer(_NumericDate):
    """`25/07/2026` (day-first, because 25 cannot be a month). `05/07/2026` is rejected as ambiguous."""

    normalizer_id = "date.numeric.unambiguous"
    version = "1"

    def normalize(self, raw_value: str) -> str:
        first, second, year = self._parts(raw_value)
        if first == second:
            return _calendar(year, second, first)
        if first > 12 >= second:
            return _calendar(year, second, first)
        if second > 12 >= first:
            return _calendar(year, first, second)
        raise NormalizationError("AMBIGUOUS_DATE_FORMAT")


class DayFirstNumericDateNormalizer(_NumericDate):
    """`05/07/2026` is 5 July 2026. Explicit day-first locale assumption (Indonesian documents)."""

    normalizer_id = "date.numeric.day-first"
    version = "1"

    def normalize(self, raw_value: str) -> str:
        day, month, year = self._parts(raw_value)
        return _calendar(year, month, day)


class MultiFormatIdrMoneyNormalizer:
    """IDR amounts in Indonesian (`1.250.000,00`) or English (`1,250,000.00`) notation.

    Rules: an optional `Rp`/`IDR` marker; a separator followed by exactly three
    digits is a thousands separator; a final separator followed by one or two
    digits is the decimal separator; grouping must be consistent. Inputs that do
    not satisfy one reading, or that name another currency, are rejected.
    """

    normalizer_id = "money.idr.multi-format"
    version = "1"
    value_type = "money"
    _FOREIGN = re.compile(r"(?i)(usd|eur|sgd|\$|€|£|¥)")

    _SHAPE = re.compile(r"(-)?\s*(?:rp\.?|idr)?\s*(-)?\s*([\d.,\s]+(?:[.,]-)?)", re.IGNORECASE)
    # Consistent thousands grouping (\2 repeats the first separator), then an optional
    # one- or two-digit decimal part with the other separator.
    _GROUPED = re.compile(r"(\d{1,3}(?:([.,])\d{3}(?:\2\d{3})*))(?:([.,])(\d{1,2}))?")
    _PLAIN = re.compile(r"(\d+)(?:([.,])(\d{1,2}))?")

    def normalize(self, raw_value: str) -> dict[str, str]:
        value = raw_value.strip()
        if self._FOREIGN.search(value):
            raise NormalizationError("UNSUPPORTED_CURRENCY")
        shape = self._SHAPE.fullmatch(value)
        if shape is None or (shape.group(1) and shape.group(2)):
            raise NormalizationError("INVALID_MONEY_FORMAT")
        negative = bool(shape.group(1) or shape.group(2))
        body = shape.group(3).replace(" ", "")
        if body.endswith((",-", ".-")):
            # Indonesian convention for whole rupiah: `Rp 1.250.000,-`
            body = body[:-2]
        grouped = self._GROUPED.fullmatch(body)
        if grouped is not None:
            if grouped.group(3) is not None and grouped.group(3) == grouped.group(2):
                raise NormalizationError("INVALID_MONEY_FORMAT")
            integer, decimals = re.sub(r"[.,]", "", grouped.group(1)), grouped.group(4) or ""
        else:
            plain = self._PLAIN.fullmatch(body)
            if plain is None:
                raise NormalizationError("INVALID_MONEY_FORMAT")
            integer, decimals = plain.group(1), plain.group(3) or ""
        amount = Decimal(integer + ("." + decimals if decimals else ""))
        return {"amount": format(-amount if negative else amount, "f"), "currency": "IDR"}


class NpwpTaxIdNormalizer:
    """Indonesian taxpayer number: 15 digits (legacy `99.999.999.9-999.999`) or 16 digits.

    Only separators `.`, `-` and spaces are removed. No check digit is computed,
    because none is published for the format; the length and characters are validated.
    """

    normalizer_id = "tax_id.npwp"
    version = "1"
    value_type = "tax_id"

    def normalize(self, raw_value: str) -> dict[str, str]:
        value = raw_value.strip()
        if not re.fullmatch(r"[\d.\-\s]+", value):
            raise NormalizationError("INVALID_TAX_ID_FORMAT")
        digits = re.sub(r"\D", "", value)
        if len(digits) == 15:
            return {"value": digits, "scheme": "NPWP15"}
        if len(digits) == 16:
            return {"value": digits, "scheme": "NPWP16"}
        raise NormalizationError("INVALID_TAX_ID_LENGTH")


def reference_normalizers() -> tuple:
    """Every normalizer the reference runtime provides, for one registry."""
    return (IdIdrMoneyNormalizer(), IsoDateNormalizer(), TrimmedIdentifierNormalizer(), TextualDateNormalizer(),
            UnambiguousNumericDateNormalizer(), DayFirstNumericDateNormalizer(), MultiFormatIdrMoneyNormalizer(),
            NpwpTaxIdNormalizer())
