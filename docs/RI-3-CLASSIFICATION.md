# RI-3 — Document Classification

## Objective

Classify a source-bound structured document into a generic document taxonomy while failing safely to `UNKNOWN`.

## Separation of concerns

Document type and business context are separate dimensions.

```text
document type: INVOICE
business domain: ACCOUNTS_PAYABLE
business process: REQUEST_FOR_PAYMENT
```

A classifier identifies document type. It does not decide whether a document is required, payable, authentic, approved or authorized.

## Abstention

`UNKNOWN` is mandatory. The reference decision abstains when:
- no candidate exists;
- the top candidate is `UNKNOWN`;
- top confidence is below the configured acceptance threshold;
- the margin between the two leading candidates is below the configured minimum margin.

Thresholds are policy/configuration and require empirical calibration. Raw model confidence is not assumed to be calibrated probability.

## Provenance and evidence

Every completed prediction records:
- model identity and version;
- taxonomy version;
- confidence;
- alternatives;
- source-bound evidence references.

Evidence references are validated against the exact StructuredDocument before the prediction is accepted.

## Security

Structured document content is untrusted model input. A classifier adapter must not interpret document text as control instructions, tool permissions, provider routing, tenant identity or authorization.

Classification output is a prediction, not an authorization decision. Downstream business systems MUST NOT use a document class alone as permission to approve or execute payment/business actions.
