from edi_reference.adapters.normalizers import IdIdrMoneyNormalizer
from edi_reference.application.field_normalization import normalize_extracted_field
from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.extraction import ExtractedField, FieldState


EV = (EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1"),)
REGISTRY = NormalizationRegistry((IdIdrMoneyNormalizer(),))


def field(state=FieldState.PRESENT, raw="Rp 1.250.000,00", evidence=EV):
    return ExtractedField(
        "total_amount", state, raw, "money", .98, evidence,
        "extractor", "1", "1",
    )


def test_normalization_is_separate_from_extraction_and_preserves_provenance():
    extracted = field()
    result = normalize_extracted_field(
        extracted, registry=REGISTRY,
        normalizer_id="money.id-ID.IDR", version="1",
    )
    assert result.extracted is extracted
    assert result.normalized.value == {"amount": "1250000.00", "currency": "IDR"}
    assert result.normalized.normalizer_id == "money.id-ID.IDR"
    assert result.normalized.normalizer_version == "1"


def test_missing_field_is_not_normalized():
    extracted = field(FieldState.MISSING, raw=None, evidence=())
    result = normalize_extracted_field(
        extracted, registry=REGISTRY,
        normalizer_id="money.id-ID.IDR", version="1",
    )
    assert result.normalized is None
