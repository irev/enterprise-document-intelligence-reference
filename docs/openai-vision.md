# OpenAI-compatible vision adapter (#39)

`edi_reference.adapters.openai_vision.OpenAICompatibleDocumentAnalyzer` implements
the internal `DocumentAnalyzer` port. It accepts one PNG or JPEG as bytes and
returns an immutable `DocumentAnalysis` containing the existing
`ClassificationPrediction` and `ExtractedField` types. This does not introduce
or change a public canonical result schema. Existing OCR and loopback text
providers remain available; removing local runtime management belongs to #44.

## Configuration and invocation

Construct the adapter with these trusted application settings:

| Argument | Meaning |
| --- | --- |
| `base_url` | Server API root, e.g. `https://vision.example.invalid/v1` |
| `provider` | Versioned `ProviderCapability` with `REMOTE_MODEL`, `APPROVED_EXTERNAL`, and both `CLASSIFICATION` and `FIELD_EXTRACTION` |
| `taxonomy` | Activated, versioned `DocumentTaxonomy` |
| `field_matrix` | Mapping of each taxonomy type to its versioned `ExtractionSchema` |
| `configurations` | Current `ProviderConfigurationSource`, checked for every attempt |
| `tenant_id`, `application_id` | Trusted caller identity used for provider authorization |
| `policy` | `ExecutionPolicy` permitting remote models and external egress |
| `classification_policy` | Existing confidence threshold and margin policy |
| `limits` | `InvocationLimits` for timeout, encoded request bytes, and response bytes |
| `api_key_env` | Optional environment variable name; the secret is read at request time |
| `max_retries` | 0–3 additional attempts, default 1 |
| `max_tokens` | Completion token limit, default 2048 |

Call `analyzer.analyze(image_bytes, media_type="image/png", observation_id="obs-synthetic")`.
The supplied image is hashed with SHA-256; returned region evidence uses that
observation ID and digest, page 1, and normalized top-left XYXY coordinates.
Construct this adapter in the application's composition layer; it is not yet a
CLI/provider-manifest selection. No credentials belong in document content.

HTTPS is required by default. An explicitly configured trusted HTTP server can
be enabled with `allow_insecure_http=True`; this sends image data and any API
key without TLS. It does not bypass provider authorization or egress policy.
Endpoint URLs cannot contain credentials, query parameters, or fragments.
Redirects are never followed. Endpoint/network allowlisting remains an
operator responsibility; document data cannot select the endpoint.

## Outcomes and limits

- Classification outside the taxonomy, below the classification threshold, or
  without a valid evidence region becomes `UNKNOWN`, with no extracted fields.
- Only the selected type's configured fields are returned. Missing, malformed,
  or unsupported values become `MISSING`; a `PRESENT` value requires a finite
  confidence and a nonempty normalized evidence region. Geometry and values
  remain model predictions, not independently verified transcription or
  business authorization. Downstream review/validation still applies.
- The API request includes the image, taxonomy, field names/types and matrix
  versions, and an instruction to treat document content as untrusted data.
- The server must support vision chat messages and JSON-object response mode.
  Invalid JSON, refusals, truncated output, and invalid envelopes fail closed.
- HTTP 429/502/503/504, connection resets and timeouts can retry, with bounded
  exponential delays starting at 0.25 seconds. Each attempt rechecks current
  provider authorization. Other failures and oversized responses are not retried.
- Timeout is the socket timeout **per attempt**, not a hard total deadline.
  Input limits cover the complete JSON request including base64 expansion;
  output limits cover the HTTP JSON envelope as well as extracted content.
- Image signatures are checked, but image decoding is left to the server.
  PDF rendering and page selection are provided by the optional
  [document image preparer](document-images.md). Preserve its source-page mapping
  when assigning derived image observations. Multipage prediction aggregation
  and API-worker integration remain separate work.
  No OCR/model/image SDK dependency is added to this analyzer or the core.

## Contract references and verification

Aligned to `irev/enterprise-document-intelligence` `SPECIFICATION.md`,
`docs/specification/NORMATIVE-MAP.md`, ADR-0005 (material evidence), ADR-0009
(explicit states and coordinates), and ADR-0011 (invocation-time authorization).
The internal result reuses repository domain types; it is not a complete public
`document-result-v2` payload. Public serialization remains a separate boundary.

Deterministic tests in `tests/unit/test_openai_vision.py` use synthetic image
data and injected HTTP connections, with no network/model access. Run them
with the repository virtual environment, together with existing invocation,
planned-provider and text-provider regression tests.
