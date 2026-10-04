# RI-5.12 — Long-Running Processing Safety

Long-running OCR, model inference, extraction, and similar work may outlive the initial processing lease. RI-5.12 adds explicit lease renewal without weakening generation fencing.

## Ownership model

A processing worker owns a claim only while all of the following remain true:

- the message identity matches;
- the claim generation matches;
- the claim status is `CLAIMED`;
- the current lease has not expired.

Lease renewal extends `lease_until`. It does not advance `claim_generation` and does not create new ownership.

An expired lease cannot be revived by renewal. Ownership after expiry must be obtained through the existing reclaim path, which advances the generation.

## Long-running processors

A lease-aware processor receives an explicit renewal callback. It may renew at safe checkpoints during work such as page batches, OCR stages, or model inference boundaries.

The callback performs a generation-fenced repository update. If ownership has expired or moved to another generation, renewal fails with `CLAIM_LEASE_LOST`.

A worker that loses its lease must not publish terminal state. Completion and failure publication remain independently fenced by generation, `CLAIMED` status, and a live lease.

## Safety properties

```text
generation N, live lease
        |
        +-- renew ----------> generation N, extended lease
        |
        +-- complete -------> COMPLETED

generation N, expired lease
        |
        +-- renew ----------> rejected
        +-- complete -------> rejected
        |
        +-- reclaim by worker B
                |
                v
          generation N+1
```

This prevents a stale long-running worker from regaining ownership merely by sending a late heartbeat.

## Reference implementation

The in-memory and PostgreSQL claim repositories implement the same renewal predicate. PostgreSQL performs the predicate and lease update atomically.

Tests cover:

- successful renewal of a live claim;
- generation remaining stable across renewal;
- stale-generation renewal rejection;
- expired-lease renewal rejection;
- application-level renewal from a long-running processor;
- prevention of terminal publication after lease loss.

The processor decides when to request renewal. Automatic background heartbeat scheduling is an operational concern and is intentionally outside this milestone.


## Failure boundary

Lease-aware processors follow the same processing-failure contract as ordinary processors: an expected document-level failure is reported with `ProcessingFailure` and may become the durable stable code `PROCESSING_FAILED` only while finalization ownership is still valid.

`CLAIM_LEASE_LOST` is an ownership/control failure, not a document-processing failure. It propagates and leaves the claim non-terminal so that normal lease expiry and reclaim semantics can recover the work. Unexpected programming defects also propagate instead of being mislabeled as `PROCESSING_FAILED`.
