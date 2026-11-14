# Security operator RBAC

## Boundary

The security-operator role is stored separately from tenant roles. Tenant owner/co-admin permissions never imply this global role. Every operator action requires an authenticated application session bound to the same verified Telegram identity.

## Provisioning and lifecycle

- The first operator must be provisioned out-of-band by a database administrator after independent identity verification. There is intentionally no HTTP bootstrap, master token, environment-variable backdoor, or self-service elevation endpoint.
- After bootstrap, an active operator can request a grant or revocation for another account.
- The requesting operator is the first approval. A second distinct active operator must explicitly approve. The requester and target cannot act as the second approver. A rejection closes the request. Requests expire after 24 hours.
- Grant/revocation requests, reasons, approvers, decisions and timestamps are persisted. Reasons must not contain credentials, tokens, personal documents or other secrets.
- An operator cannot grant, revoke or modify their own role. Tenant roles cannot be used to satisfy operator RBAC.
- Emergency operator changes use the same two-operator approval rule; no single-admin override is exposed.

## Recovery decisions

An active operator may record one approve/reject decision for a UUID recovery case and account. The case identifier is opaque in this release; the recovery state machine and case lifecycle are deliberately deferred. The target account must have a verified recovery contact and cannot be the operator's own Telegram identity. A unique case/operator constraint prevents duplicate decisions.

## Hard limits

Operator decisions are audit inputs only. This API does not shorten the 24-hour hold, issue a recovery token, create a session, revoke Passkeys, or activate recovery. It does not make tenant owners/co-admins global identity administrators. Recovery remains disabled until the notification/veto flow, recovery state machine, PostgreSQL concurrency tests, real-device E2E and independent security review are complete.
