# RI-1.6 — Reliable and Secure Dispatch

## Objective

Close the crash window between accepting an inbound document and scheduling processing, while strengthening source-acquisition boundaries before real network adapters are introduced.

## Transactional outbox

Production persistence MUST commit the accepted inbound state and its processing outbox message atomically in one durable transaction (or provide equivalent atomic semantics).

```text
transaction
  update inbound -> ACCEPTED
  insert outbox message -> PENDING
commit

outbox publisher
  PENDING -> publish -> PUBLISHED
```

A crash after commit does not lose the processing intent. A crash after broker publish but before marking PUBLISHED can publish again; delivery is therefore at-least-once and processing consumers MUST deduplicate by stable message identity.

Queue messages contain identifiers/content identity, not document bytes or credentials.

## Security boundaries

Before any network adapter performs I/O:
- direct upload cannot name a remote resource;
- managed connector resources are opaque resource identifiers, not caller-controlled endpoints;
- signed URL references require HTTPS and cannot embed username/password;
- source credentials are never durable source metadata.

A real HTTP adapter MUST additionally enforce destination allow-list policy, DNS/IP validation, redirect re-validation, prohibited address ranges, bounded response size, timeouts and connection limits. Static URL parsing alone is not an SSRF defense.

Managed connector endpoints and credentials belong to trusted control-plane configuration. Callers select an authorized connector/resource, not arbitrary connection parameters.

## Failure and audit

Operational failures use stable non-secret error codes. Exception text, credentials, signed URL query values and raw document bytes MUST NOT be written to generic audit or telemetry.

Outbox retry policy is deployment configuration. Exhaustion transitions to a separately observable dead-letter state without changing the immutable processing outcome of already completed work.
