# ADR-0001 — Storage references and just-in-time grants instead of caller-supplied URLs

- Status: accepted for implementation (RI-6.0 phase B)
- Date: 2026-10-09
- Supersedes: the `SIGNED_URL` submission mode in RI-6.0 §4 (design only, never implemented)

## Context

RI-6.0 originally proposed that an application could submit `{"source": {"method": "SIGNED_URL", "url": …}}`. The service would fetch the URL if its host was on an allow-list, and keep the URL with the job.

The tenant-owned storage blueprint adopted for this work states the opposite as MUST rules:

- arbitrary caller-supplied URLs are never fetched (NET-001);
- bearer URLs never enter job records, queues, logs or errors (SEC-007, ADR-010 there);
- read grants are short-lived, exact-object, requested just in time (SEC-004/005);
- the fetcher enforces HTTPS, no redirects, real DNS/IP validation and bounded transfer (NET-002…005);
- integrity is verified before processing (AC-05).

## Decision

1. **Storage connections.** An administrator registers a *storage connection* for a tenant. It records:
   - the HTTPS URL of the tenant's **grant broker**;
   - the exact storage **origins** (scheme, host, port) a grant may point to;
   - whether those origins may be on private or loopback networks (explicit per connection, off by default);
   - a reference to the broker authentication secret, which is kept outside the database.
2. **Submission.** Applications submit `{"source": {"method": "STORAGE_REFERENCE", "storage_connection_id", "object_id", "sha256", "version_id"?}}`:
   - the connection must belong to the caller's tenant;
   - `object_id` is opaque and is never used as a URL or a path;
   - `sha256` is required, so integrity can always be verified (stricter than the blueprint's "digest or trustworthy version").
3. **Just-in-time grant.** Immediately before download, the worker asks the broker for a grant. The request is HMAC-signed and bound to `(tenant, connection, document, object, version, operation=GET, nonce, timestamp)`. The grant (URL, expiry, optional headers) exists only in worker memory for that fetch. It is never stored, logged, audited or returned.
4. **Restricted fetcher.** For every fetch it:
   - accepts only HTTPS URLs on a registered origin, with no userinfo or fragment;
   - resolves DNS once and rejects loopback, private, link-local (including cloud metadata), multicast and reserved addresses unless the connection explicitly allows private networks;
   - connects to the **resolved IP** (pinned) while verifying the TLS certificate for the hostname, which defeats DNS rebinding;
   - refuses redirects;
   - enforces connect and total timeouts and the application's byte limit;
   - verifies `sha256` before the bytes reach OCR.
5. **Error codes.** Failures map to stable codes: `SOURCE_ACCESS_DENIED`, `SOURCE_OBJECT_MISSING`, `SOURCE_GRANT_EXPIRED`, `SOURCE_HOST_FORBIDDEN`, `SOURCE_REDIRECT_REFUSED`, `SOURCE_TOO_LARGE`, `SOURCE_CHECKSUM_MISMATCH`, `SOURCE_UNREACHABLE`, `SOURCE_BROKER_INVALID_RESPONSE`.
   - **Retried within the bounded job attempts:** transient failures (unreachable, timeouts, `5xx`).
   - **Refreshed once:** a grant refused by storage (`401`/`403`), because most providers do not distinguish expiry from denial. If storage also refuses the fresh grant, the failure is `SOURCE_ACCESS_DENIED` (permanent); it is never refreshed again (blueprint §3.3).
   - **Recorded immediately as `FAILED_SAFE` with no extraction:** access denied, missing object, policy violations and checksum mismatch.
6. **Caller URLs.** `SIGNED_URL` from a caller is rejected permanently with `CALLER_URL_NOT_ACCEPTED`.
7. **Single-use.** No single-use guarantee is claimed for grants; a native signed URL can be reused until it expires (blueprint ADR-006, AC-04).

## Alternatives considered

- **Keep caller URLs with a host allow-list.** Rejected: it violates NET-001 and SEC-007, and turns every application into a source of fetch destinations.
- **Let the service presign storage URLs itself** (for example with S3 credentials). Rejected for the initial release: the service would have to hold storage credentials (SEC-003), and each provider needs its own adapter. A provider-specific adapter can be added later behind the same `GrantBroker` port (blueprint §9).

## Consequences

- Tenants run a grant broker. A small reference broker for development and tests is provided (`scripts/reference_grant_broker.py`). It is not a production component.
- Application-level validation is not the only egress barrier. NET-003 still requires host firewall or proxy egress policy in production, which this repository cannot enforce.
- The broker secret is a file under the panel state directory, readable only by the service account. A secrets manager or KMS is the production requirement (blueprint §6) and is out of scope here.
- Batch manifests, result push and cancellation (blueprint §3.2, §8) are not part of this decision.

## Deviations from the blueprint

The blueprint's endpoint names, payloads and state machine are proposed reference contracts (blueprint §0). This repository keeps its own, and that is a deliberate choice:

| Blueprint | This implementation | Reason |
|---|---|---|
| `POST /v1/document-jobs`, `GET …/result` | `POST /v1/documents` (upload or `STORAGE_REFERENCE`), `GET /v1/documents/{id}/results/{version}` | One resource for both submission modes; results are immutable versions (AGENTS rules 8–9). |
| OAuth 2.0 workload tokens, optional mTLS | Per-application API keys bound to tenant, application and scopes | Phase A decision D2; tenant and application still come only from the credential (SEC-001). An OAuth adapter can be added without changing authorization. |
| States `awaiting_grant`, `fetching`, `quarantined`, `scanning`, `review_required` | `ACCEPTED → PROCESSING → COMPLETED / FAILED_SAFE`; every result has `review.required: true` | The finer states are not observable through the API yet. |
| Grant request through DI endpoint `/v1/grants/{id}/issue` | DI calls the tenant broker (allowed by blueprint §4, "may be inverted") | No inbound path for grants. |

## Acceptance criteria not yet met

Against blueprint §12, after phase B:

- **Met:**
  - AC-03 (no bearer values in the database, files or results; tested);
  - AC-05 (digest mismatch gives `FAILED_SAFE` with no extraction);
  - AC-07 (idempotency, fingerprint conflict, leases);
  - AC-10 (no fabricated fields; evidence, provenance and review flag).
- **Partly met:**
  - AC-01: tenant and application checks exist for documents, connections and reprocess; there are no batch or cancel endpoints yet.
  - AC-02: enforced in the application, tested; host egress policy (NET-003) is the deployment's job.
  - AC-04: exact-object grants, one refresh; `version_id` is passed to the broker but integrity rests on `sha256`.
  - AC-08: the model endpoint is loopback-only, but this is not yet tested on the storage-reference path.
- **Not met:**
  - **AC-06**: batch manifests.
  - **AC-09**: quarantine and malware scanning before OCR (FILE-001). Fetched bytes go to OCR after a type check only.
  - **AC-11**: fetched bytes are kept in the panel's content-addressed store, like uploads, with no retention policy (DATA-004/005; blueprint ADR-005 is open). This must be decided before documents with payment or bank data are processed in production.
  - **AC-12**: signed artifacts and policies.
