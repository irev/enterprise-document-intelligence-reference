"""Explicit registry for deterministic, versioned normalizers."""

from edi_reference.domain.normalization import NormalizedValue, NormalizationError, Normalizer


class NormalizationRegistry:
    def __init__(self, normalizers: tuple[Normalizer, ...]):
        self._normalizers: dict[tuple[str, str], Normalizer] = {}
        for normalizer in normalizers:
            key = (normalizer.normalizer_id, normalizer.version)
            if key in self._normalizers:
                raise ValueError("DUPLICATE_NORMALIZER")
            self._normalizers[key] = normalizer

    def normalize(self, raw_value: str, *, normalizer_id: str, version: str) -> NormalizedValue:
        normalizer = self._normalizers.get((normalizer_id, version))
        if normalizer is None:
            raise NormalizationError("NORMALIZER_NOT_FOUND")
        try:
            value = normalizer.normalize(raw_value)
        except NormalizationError:
            raise
        except Exception:
            raise NormalizationError("NORMALIZATION_FAILED") from None
        return NormalizedValue(value, normalizer.value_type, normalizer.normalizer_id, normalizer.version)
