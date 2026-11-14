# Outbound email transport

Optional SMTP transport for future security notifications and recovery-contact
verification. Delivery is disabled unless both `SMTP_HOST` and
`SMTP_FROM_ADDRESS` are configured.

## Free-first operation

The project provisions no vendor, paid plan, domain, or account. The operator
may use an SMTP server they already control. Local development can use a local
test sink such as Mailpit; CI must never send real messages.

Production deliverability (DNS, SPF, DKIM, DMARC, reputation, and provider
limits) remains the operator's responsibility. SMTP submission does not prove
inbox delivery or ownership of an address.

## Configuration

Configure through deployment environment variables or a secret store:

- `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM_ADDRESS`
- `SMTP_STARTTLS=true` (default) or `SMTP_SSL=true` for implicit TLS; never both
- `SMTP_USERNAME` and `SMTP_PASSWORD` together when authentication is required
- `SMTP_TIMEOUT_SECONDS` (1–60; default 10)

Leave host and sender empty to disable email. Sending while disabled raises
`EmailTransportNotConfigured`; it is never reported as success. Partial or
contradictory configuration is rejected.

## Security boundaries

- SMTP credentials belong only in deployment secrets, never in Git, fixtures,
  issues, logs, or message content.
- The transport sends plain text and normalizes connection/authentication
  failures without exposing provider diagnostics.
- It does not create/verify contacts, authorize recovery, create sessions, or
  issue tokens.
- It has no retry or idempotency logic. The notification/outbox layer must
  persist attempts, deduplicate stable event keys, apply bounded retry, and fail
  closed on critical delivery failure. SMTP cannot guarantee exactly-once send.
- A successful SMTP submission is not proof that a user controls an address;
  verification requires a separate short-lived, single-use challenge.
