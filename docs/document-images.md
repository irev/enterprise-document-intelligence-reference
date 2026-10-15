# Document image preparation (#40)

## Baseline and dependencies

Audited baseline: `c69e8f5` on `code/workspace`. The #39 vision adapter already
exists and consumes a single PNG/JPEG. The older Paddle page worker renders
inside its own OCR runtime; it is not a reusable bounded vision input adapter.

#40 adds an internal `DocumentImagePreparer` port and the opt-in
`PdfiumDocumentImagePreparer` adapter. It does not replace the existing OCR
pipeline, wire the vision provider into the API worker, aggregate predictions
across pages, or remove runtime management. Runtime removal (#44) must wait for
the replacement pipeline to be integrated and verified. Tenant field matrices
(#43) and advisory output (#41) remain separate dependencies of those features,
not prerequisites for rendering. No public result schema or historical result
is changed.

Specification references checked: `SPECIFICATION.md`,
`docs/specification/NORMATIVE-MAP.md`, ADR-0005 (material evidence), and ADR-0009
(explicit states and normalized coordinates) in the specification repository.

## Use

Install `pip install -e ".[vision]"` in the repository virtual environment.
PDFium and Pillow are adapter-only optional runtime dependencies. The dev extra
includes them plus pypdf to generate synthetic, encrypted test PDFs; the default
CI test suite exercises real rendering rather than skipping these tests.

```python
from edi_reference.adapters.document_images import (
    ImagePreparationLimits,
    PdfiumDocumentImagePreparer,
)

preparer = PdfiumDocumentImagePreparer(ImagePreparationLimits(dpi=150, max_pages=20))
prepared = preparer.prepare(pdf_bytes, media_type="application/pdf")
# Explicit selection, retaining original 1-based page numbers and caller order:
selected = preparer.prepare(pdf_bytes, media_type="application/pdf", page_numbers=(2, 1))
```

Each page contains JPEG bytes, its SHA-256, dimensions, and `source_page_number`.
The batch carries the original source SHA-256, total page count, `complete`, and
an immutable rendering recipe (algorithm, PDFium/Pillow versions, and limits).
PNG/JPEG inputs are decoded/validated then passed through byte-for-byte, including
their original media type; animated/multiframe images are rejected.

The default `page_selection="all"` rejects documents above `max_pages`.
`page_selection="first"` explicitly selects the first N pages. Explicit
`page_numbers` overrides that strategy, must be unique and in range, and must
respect `max_pages`. A partial selection returns `complete=False`: consumers
must not interpret it as analysis of the entire source.

## Resource limits and failures

| Setting | Default |
| --- | --- |
| DPI | 150 (allowed 1–600) |
| Selected pages | 20 |
| Input bytes | 20,000,000 |
| JPEG/image bytes per page | 5,000,000 |
| Total image output bytes | 20,000,000 |
| Maximum width or height | 4096 pixels |
| Pixels per image | 16,000,000 |
| JPEG quality | 85 (allowed 1–95) |

Dimensions are checked before native rendering, and encoded writes are bounded.
An oversized page fails explicitly instead of silently lowering resolution.
The adapter returns no partial batch on failure and closes native page, bitmap,
and document resources. Calls through this adapter serialize PDFium access.

`DocumentImageError.code` contains stable codes: `PDF_ENCRYPTED`, `INVALID_PDF`,
`INVALID_IMAGE`, `EMPTY_DOCUMENT`, `UNSUPPORTED_DOCUMENT_MEDIA_TYPE`,
`IMAGE_MEDIA_TYPE_MISMATCH`, `MULTIFRAME_IMAGE_UNSUPPORTED`,
`INVALID_PAGE_SELECTION`, `DOCUMENT_PAGE_LIMIT_EXCEEDED`,
`DOCUMENT_INPUT_LIMIT_EXCEEDED`, `IMAGE_DIMENSION_LIMIT_EXCEEDED`,
`IMAGE_OUTPUT_LIMIT_EXCEEDED`, or `IMAGE_PREPARATION_DEPENDENCY_UNAVAILABLE`.
Password-protected PDFs, including encrypted files with an empty user password,
are rejected. Invalid PDFs use PDFium's parser outcome; recoverable malformed
files may be accepted by PDFium. This is not strict PDF conformance validation.

These are raster/output limits, not a hard CPU or native-parser memory limit.
Production processing of hostile PDFs still needs process isolation and worker
deadlines. Total base64/JSON request size is enforced separately by the existing
vision adapter's invocation limits.

## Evidence boundary with #39

Use `application.image_derivation.prepare_image_derivation` with the existing
`SourceObservation` and `ProcessingRunBinding` plus trusted tenant/application
identity. It verifies scope, source byte length/digest and the run binding before
rendering, then persists the entire image batch through an explicit repository
port. `SqliteImageDerivationRepository` uses its own prefixed tables and can share
the API DB path; no existing result table or public schema is changed.

Pass persisted pages to `analyzer.analyze(page.content,
media_type=page.media_type, observation_id=saved.image_observation_id(page))`.
Persistence must succeed before invoking a separately authorized analyzer.

Persistence is atomic across metadata and all image bytes. Database triggers
reject updates/deletes. Exact retries reuse the same identities; a changed recipe,
page selection or output on the same run raises `IMAGE_DERIVATION_CONFLICT`.
Reprocessing requires a new run and creates new image observation IDs. Reads
require both tenant and application and validate stored image hashes/identities.
The stored images contain document data and need the same filesystem/backup
protection as source content. Rendering and persistence do not authorize egress.

The current analyzer returns page 1 relative to the **derived image** and hashes
that image. Preserve that evidence and the source mapping; do not relabel the
image digest as the original PDF digest or silently treat every result as source
page 1. Persisted derivation lineage is now available as an internal component;
merging multipage predictions and wiring the API worker remain pending in the
[dependency worklist](VISION-INTEGRATION-TODO.md).

## Verification

`tests/unit/test_document_images.py` uses synthetic PDFs/images and no model or
network. It covers real JPEG rendering, rotation, explicit page selection and
partial coverage, byte/pixel/page budgets, corrupt and encrypted PDFs (including
empty user passwords), passthrough validation, resource cleanup on failure,
missing dependencies, and compatibility with the mocked #39 analyzer.
