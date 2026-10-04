# RI-5.9 — Observation Identity Dispatch

Processing dispatch is bound to an immutable source observation identity.

A content digest is an integrity attribute. It is not the identity of a source observation because identical bytes may legitimately occur in different documents, acquisitions, tenants, or applications.

The reference therefore uses `observation_id` as the authoritative processing input identity:

1. successful acquisition produces a scoped source observation;
2. accepted inbound state, the source observation, and the processing outbox message are committed atomically;
3. the outbox message carries the observation identity;
4. the processing consumer resolves that exact observation before claiming work;
5. tenant and application scope are checked against the resolved observation;
6. the processing claim records both the observation identity and its digest.

The digest remains useful for integrity verification and reproducibility, but processing lineage does not infer observation identity from the digest or from `payload_ref`.

## Failure properties

If observation persistence or outbox insertion fails, inbound acceptance is not committed.

A processing message without an observation identity is rejected. A missing observation or scope mismatch is also rejected before processing begins.

## Transitional note

`payload_ref` remains on the outbox contract for content-location compatibility. RI-5.9 deliberately does not use its digest-shaped value as the authoritative observation identity. Future content storage work may replace that representation without changing lineage identity.
