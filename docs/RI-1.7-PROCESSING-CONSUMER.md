# RI-1.7 — Processing Consumer Reliability

## Objective

Make at-least-once dispatch safe before selecting a database, broker or worker framework.

## Deduplication identity

The outbox `message_id` is the delivery deduplication key. Redelivery of a completed message returns the existing completed claim and MUST NOT execute document processing again.

A stable `processing_run_id` is created on the first successful claim. Lease recovery retains that run identity.

## Lease semantics

A worker claims processing for a bounded interval. While the lease is active, another delivery does not execute the processor. After lease expiry, work may be reclaimed.

Production repositories MUST implement claim creation/reclaim with atomic compare-and-set, row locking, unique constraints or equivalent concurrency semantics. The in-memory adapter proves behavior only; it is not a production concurrency primitive.

## Security

Messages are treated as untrusted transport input even when received from an internal broker:
- message type is allow-listed;
- content references are structurally validated;
- tenant/application scope comes from durable service-created dispatch state, not document text;
- provider exception details are not persisted as failure messages;
- raw source bytes and credentials are not broker payloads.

Broker authentication, authorization, encryption and network policy are deployment concerns but MUST be configured for production.

## Delivery guarantee

The architecture assumes at-least-once delivery, not exactly-once transport. Correctness comes from durable idempotency, stable message identity, atomic claims and immutable completed results.
