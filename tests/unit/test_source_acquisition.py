import pytest

from edi_reference.domain.source import SourceChangedError, verify_reprocess_source


def test_reprocess_accepts_identical_observed_bytes() -> None:
    digest = "a" * 64
    verify_reprocess_source(expected_sha256=digest, actual_sha256=digest.upper())


def test_reprocess_rejects_changed_source() -> None:
    with pytest.raises(SourceChangedError, match="SOURCE_CHANGED"):
        verify_reprocess_source(
            expected_sha256="a" * 64,
            actual_sha256="b" * 64,
        )
