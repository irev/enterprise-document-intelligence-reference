# RI-2.2 — Quality Assessment and OCR Decision

## Objective

Route pages to OCR using explicit, explainable quality signals rather than a single magic threshold.

## Page-level signals

The reference contract records:
- native character count;
- native text coverage;
- image coverage;
- page rotation;
- detected skew;
- text origin.

Coverage values are normalized to [0,1]. Rotation is canonicalized to 0/90/180/270 degrees.

## Decision

Each page receives one of:
- `NOT_REQUIRED`
- `REQUIRED`
- `REVIEW_REQUIRED`

The reference policy requires multiple strong signals before automatically requiring OCR. A single weak signal or a borderline measurement fails safely to `REVIEW_REQUIRED`.

This is deliberately not a claim that the initial thresholds are universally correct. Thresholds are configuration and must be calibrated against representative documents.

## Why page-level routing

A PDF can contain both digitally generated and scanned pages. Document-level all-or-nothing OCR wastes resources and can degrade high-quality native text.

```text
page 1 native text -> keep native
page 2 scanned      -> OCR
page 3 native text  -> keep native
page 4 uncertain    -> review/policy
```

## Security and correctness

Quality metrics are observations, not authorization or business truth. Document content cannot alter OCR policy.

OCR output must not silently overwrite native text. The canonical result records text origin and provenance so later evidence can distinguish native, OCR and mixed content.

A remote OCR route remains a controlled data-egress decision and cannot be selected merely because document text asks for an external provider.
