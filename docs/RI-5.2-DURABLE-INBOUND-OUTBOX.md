# RI-5.2 — Durable Inbound and Transactional Outbox

The PostgreSQL reference now persists inbound request identity and processing dispatch intent.

The database enforces scoped idempotency uniqueness on tenant, application and idempotency key. Accepted inbound state and its PROCESS_DOCUMENT outbox message are committed in one PostgreSQL transaction.

The integration suite proves both sides of the atomicity guarantee:
- successful acceptance persists ACCEPTED and PENDING together;
- a forced outbox insertion failure rolls the transaction back, leaving the inbound record ACQUIRING rather than falsely ACCEPTED.

The outbox is durable dispatch intent, not proof that a consumer received the message. Publication and delivery acknowledgement remain separate lifecycle concerns.

Original document bytes remain outside these tables.
