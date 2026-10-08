import pytest

from edi_reference.adapters.normalizers import (
    DayFirstNumericDateNormalizer,
    MultiFormatIdrMoneyNormalizer,
    NpwpTaxIdNormalizer,
    TextualDateNormalizer,
    UnambiguousNumericDateNormalizer,
    reference_normalizers,
)
from edi_reference.application.panel_config import KNOWN_NORMALIZERS
from edi_reference.domain.normalization import NormalizationError


@pytest.mark.parametrize(("raw", "expected"), [
    ("15 Juli 2026", "2026-07-15"), ("15 Jul 2026", "2026-07-15"), ("1 Januari 2026", "2026-01-01"),
    ("20 September 2026", "2026-09-20"), ("September 20, 2026", "2026-09-20"), ("Sep 20 2026", "2026-09-20"),
    ("31 Desember 2026", "2026-12-31"), ("9 Nopember 2026", "2026-11-09"), ("15-Agu-2026", "2026-08-15"),
    ("  15   Mei  2026 ", "2026-05-15"), ("15Juli 2026", "2026-07-15"), ("15Maret2026", "2026-03-15"),
])
def test_textual_dates(raw, expected):
    assert TextualDateNormalizer().normalize(raw) == expected


@pytest.mark.parametrize(("raw", "code"), [
    ("31 Februari 2026", "INVALID_CALENDAR_DATE"), ("15 Juli", "INVALID_DATE_FORMAT"),
    ("Rabu, 15 Juli 2026", "INVALID_DATE_FORMAT"), ("15 Jully 2026", "UNKNOWN_MONTH_NAME"),
    ("2026-07-15", "INVALID_DATE_FORMAT"), ("15/07/2026", "INVALID_DATE_FORMAT"),
])
def test_textual_dates_reject_rather_than_guess(raw, code):
    with pytest.raises(NormalizationError) as failure:
        TextualDateNormalizer().normalize(raw)
    assert failure.value.code == code


def test_numeric_dates_are_only_accepted_when_unambiguous():
    unambiguous = UnambiguousNumericDateNormalizer()
    assert unambiguous.normalize("25/07/2026") == "2026-07-25"
    assert unambiguous.normalize("07/25/2026") == "2026-07-25"
    assert unambiguous.normalize("05.05.2026") == "2026-05-05"
    for raw in ("05/07/2026", "12-11-2026"):
        with pytest.raises(NormalizationError) as failure:
            unambiguous.normalize(raw)
        assert failure.value.code == "AMBIGUOUS_DATE_FORMAT"
    with pytest.raises(NormalizationError):
        unambiguous.normalize("05/07-2026")  # mixed separators


def test_day_first_is_an_explicit_locale_choice():
    day_first = DayFirstNumericDateNormalizer()
    assert day_first.normalize("05/07/2026") == "2026-07-05"
    with pytest.raises(NormalizationError) as failure:
        day_first.normalize("07/25/2026")
    assert failure.value.code == "INVALID_CALENDAR_DATE"


@pytest.mark.parametrize(("raw", "amount"), [
    ("Rp 1.250.000,00", "1250000.00"), ("Rp1,250,000.00", "1250000.00"), ("IDR 349,000.00", "349000.00"),
    ("1.250", "1250"), ("1,250", "1250"), ("12,50", "12.50"), ("12.5", "12.5"), ("645.181.835,00", "645181835.00"),
    ("Rp0.00", "0.00"), ("-Rp349,000.00", "-349000.00"), ("Rp -1.000", "-1000"), ("2500000", "2500000"),
    ("Rp 645.181.835,-", "645181835"), ("1.250.000.-", "1250000"),
])
def test_money_in_indonesian_or_english_notation(raw, amount):
    assert MultiFormatIdrMoneyNormalizer().normalize(raw) == {"amount": amount, "currency": "IDR"}


@pytest.mark.parametrize(("raw", "code"), [
    ("-Rp349,000.000", "INVALID_MONEY_FORMAT"), ("1.250,000", "INVALID_MONEY_FORMAT"), ("1.250.00", "INVALID_MONEY_FORMAT"),
    ("1,250.000,00", "INVALID_MONEY_FORMAT"), ("USD 100.00", "UNSUPPORTED_CURRENCY"), ("$5", "UNSUPPORTED_CURRENCY"),
    ("Rp", "INVALID_MONEY_FORMAT"), ("--5", "INVALID_MONEY_FORMAT"), ("seratus ribu", "INVALID_MONEY_FORMAT"),
    ("645.181.835.00", "INVALID_MONEY_FORMAT"), ("1.250,-5", "INVALID_MONEY_FORMAT"),
])
def test_money_rejects_inconsistent_or_foreign_values(raw, code):
    with pytest.raises(NormalizationError) as failure:
        MultiFormatIdrMoneyNormalizer().normalize(raw)
    assert failure.value.code == code


def test_npwp():
    npwp = NpwpTaxIdNormalizer()
    assert npwp.normalize("01.234.567.8-901.234") == {"value": "012345678901234", "scheme": "NPWP15"}
    assert npwp.normalize("0123 4567 8901 2345") == {"value": "0123456789012345", "scheme": "NPWP16"}
    for raw, code in (("NPWP 01.234", "INVALID_TAX_ID_FORMAT"), ("123456789", "INVALID_TAX_ID_LENGTH"),
                      ("002241867744100000000", "INVALID_TAX_ID_LENGTH")):
        with pytest.raises(NormalizationError) as failure:
            npwp.normalize(raw)
        assert failure.value.code == code


def test_every_configurable_normalizer_exists_at_runtime():
    provided = {f"{n.normalizer_id}@{n.version}" for n in reference_normalizers()}
    assert set(KNOWN_NORMALIZERS) <= provided
