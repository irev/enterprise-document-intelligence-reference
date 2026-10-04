# RI-1.5 — Acquisition and Inbound Foundation

## Goal

Establish the application boundary between multiple consumer applications and deterministic document ingestion without choosing an HTTP framework, database, secret store or acquisition protocol library.

## Flow

```text
authenticated ApplicationPrincipal
  -> application/tenant authorization
  -> InteractionContext
  -> SourceReference
  -> SourceAcquirer port
  -> temporary AcquiredSource bytes
  -> RI-1 deterministic validation/hash
  -> AcquisitionEvent
  -> audit sink
  -> later processing dispatch
```

## Boundaries

Authentication proves the caller identity outside this use case. RI-1.5 receives an `ApplicationPrincipal` and independently authorizes it against the requested application/tenant context.

A caller cannot gain tenant access by changing payload identifiers.

`SourceAcquirer` is a port. HTTP, signed URL, SFTP, object storage and application API clients belong in adapters.

`AcquiredSource.content` is temporary processing material. The audit event stores content identity and source metadata, not document bytes.

## Audit projection

An inbound monitor can project:
- tenant/application/correlation identity;
- acquisition method;
- outcome and stable failure code;
- content digest, byte length and detected media type when accepted;
- external source version/ETag when available;
- connector configuration version.

Secrets and raw document contents are excluded.

## Deferred

- transport authentication mechanism;
- durable application/tenant registry;
- durable idempotency/inbox;
- durable acquisition repository;
- real network connectors;
- secret management;
- processing queue/worker;
- control-panel HTTP/UI.

Those are implementation adapters or later lifecycle concerns and must not be hidden inside the domain model.


## Durable inbound lifecycle foundation

The reference implementation now defines a repository/dispatcher boundary:

```text
RECEIVED -> ACQUIRING -> ACCEPTED
                       -> REJECTED
                       -> UNSUPPORTED
                       -> FAILED

ACCEPTED -> ProcessingDispatch
```

Submission requires both `request_id` and `idempotency_key`. Idempotency is scoped by `(tenant_id, application_id, idempotency_key)`; replay returns the existing inbound record and MUST NOT reacquire or redispatch the document.

The current repository and dispatcher are deterministic in-memory adapters used to prove semantics. They are not a production durability claim. A production adapter must preserve the same uniqueness and state-transition behavior using its chosen durable technology.

The processing dispatch carries content identity (SHA-256) and correlation identities, not source document bytes.
