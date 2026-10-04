# RI-3.1 — Information Extraction

## Objective

Extract typed fields without collapsing source text, normalized values, field state and evidence into a single ambiguous value.

## Field representation

Each field records:
- stable field name;
- explicit field state;
- raw source value;
- normalized/typed value;
- value type;
- field confidence;
- evidence references;
- extractor identity/version;
- extraction schema version.

## Field states

Initial reference states are:
- `PRESENT`: source evidence supports a value;
- `MISSING`: no supported value was found;
- `EXPLICIT_NULL`: the source explicitly communicates no applicable/value state;
- `INVALID`: source content exists but cannot satisfy the field contract.

`MISSING` is not the same as null, empty string, zero or extraction failure.

A `PRESENT` field requires evidence. A `MISSING` field cannot carry an invented raw/normalized value. `EXPLICIT_NULL` and `INVALID` require source evidence.

## Raw and normalized values

Normalization never destroys the observed representation.

Example:

```text
raw_value        = "Rp 1.250.000,00"
normalized_value = 1250000
value_type       = "money"
```

Currency, date and identifier normalization are separate deterministic contracts and will be versioned independently.

## Safety

Extractor output is a machine claim. It is not authoritative business data merely because it has a typed value or high confidence.

The extractor cannot manufacture a present field without evidence, cannot change tenant/application scope, and cannot use document text to alter extraction schema or authorization policy.

Confidence is retained as model/provider output and is not assumed calibrated unless separately demonstrated.
