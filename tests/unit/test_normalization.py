import pytest

from edi_reference.adapters.normalizers import IdIdrMoneyNormalizer, IsoDateNormalizer, TrimmedIdentifierNormalizer
from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.domain.normalization import NormalizationError


REGISTRY = NormalizationRegistry((IdIdrMoneyNormalizer(), IsoDateNormalizer(), TrimmedIdentifierNormalizer()))


def test_idr_normalization_is_deterministic_and_exact():
    result = REGISTRY.normalize("Rp 1.250.000,00", normalizer_id="money.id-ID.IDR", version="1")
    assert result.value == {"amount": "1250000.00", "currency": "IDR"}
    assert result.normalizer_version == "1"


def test_money_does_not_guess_ambiguous_foreign_format():
    with pytest.raises(NormalizationError, match="INVALID_MONEY_FORMAT"):
        REGISTRY.normalize("1,250,000.00", normalizer_id="money.id-ID.IDR", version="1")


def test_iso_date_does_not_guess_local_date_order():
    with pytest.raises(NormalizationError, match="INVALID_DATE_FORMAT"):
        REGISTRY.normalize("04/10/2026", normalizer_id="date.iso-8601", version="1")


def test_identifier_preserves_semantics_while_trimming():
    result = REGISTRY.normalize("  INV-001  ", normalizer_id="identifier.trimmed", version="1")
    assert result.value == "INV-001"


def test_unknown_normalizer_fails_explicitly():
    with pytest.raises(NormalizationError, match="NORMALIZER_NOT_FOUND"):
        REGISTRY.normalize("x", normalizer_id="unknown", version="1")


@pytest.mark.parametrize("value", ["2026-10-4", "2026-1-04", "20261004", "2026-W40-7"])
def test_iso_date_requires_exact_calendar_date_shape(value):
    with pytest.raises(NormalizationError, match="INVALID_DATE_FORMAT"):
        REGISTRY.normalize(value, normalizer_id="date.iso-8601", version="1")
