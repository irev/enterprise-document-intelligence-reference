# RI-3.2 — Deterministic Normalization Registry

## Objective

Normalize observed field text through explicit, versioned deterministic contracts rather than model-specific implicit conversion.

## Registry identity

A normalizer is selected by `normalizer_id + version`. Reprocessing can therefore reproduce the exact conversion contract used by an earlier result.

Initial reference examples:
- `money.id-ID.IDR@1`
- `date.iso-8601@1`
- `identifier.trimmed@1`

These are implementation examples, not mandatory platform technologies or universal locale assumptions.

## No guessing

A normalizer only accepts syntax covered by its declared contract.

For example, the ID/IDR normalizer accepts `Rp 1.250.000,00` under an explicit Indonesian-format contract. It rejects `1,250,000.00` rather than silently guessing another locale.

Likewise the ISO date normalizer rejects `04/10/2026` because day/month ordering is not explicit in that contract.

Ambiguous conversion must be resolved by an explicit profile/locale-aware contract, additional evidence, or review.

## Numeric representation

The reference money normalizer uses decimal arithmetic and serializes the canonical amount as a decimal string. Financial amounts must not depend on binary floating-point representation.

## Relationship to extraction

Extraction preserves the raw observed value and evidence. Normalization produces a typed canonical value plus normalizer provenance. A normalization failure does not erase the raw source observation and must not invent a replacement value.
