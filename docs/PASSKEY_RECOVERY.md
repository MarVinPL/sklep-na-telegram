# Passkey recovery v1

## Status and scope

This document specifies the approved recovery policy for Issue #16. It is a design contract for the backend, Telegram Mini App, WWW panel and operator workflow. It does not enable recovery by itself and does not authorize production deployment.

Recovery codes are intentionally excluded from v1. A user should register at least two Passkeys on separate devices while authenticated with an existing Passkey. Telegram `initData`, Telegram ID, username, possession of the same phone, and a recovery URL are not identity proof.

## Security invariants

1. Fail closed: if an independent recovery contact or the required approvers are unavailable, automated recovery is unavailable.
2. No PIN, static password, recovery code, or Telegram-only fallback.
3. Starting a case never creates an application session and never reveals whether a Telegram identity or Passkey exists.
4. Recovery approval is not authentication. The final ceremony must verify a newly registered Passkey before any session is created.
5. Recovery tokens are random, purpose-bound, user-bound, single-use, stored only as hashes, short-lived, and consumed atomically.
6. A veto blocks finalization and places the case into manual review; no AI or operator helper can override it.
7. All existing sessions and all previously registered Passkeys are revoked atomically only after successful registration of the replacement Passkey.
8. Audit events contain identifiers and outcome metadata only. Never log Telegram initData, tokens, WebAuthn payloads, private keys, contact proofs, or recovery secrets.

## Enrollment prerequisites

- Require at least two active Passkeys, with the user encouraged to keep them on separate devices.
- The independent recovery contact must be registered and verified before an incident, through a separately authenticated process. It must not be added or changed during an open recovery case.
- The contact must be independent of the Telegram account being recovered. SMS alone is not sufficient because of SIM-swap risk.
- The platform must maintain a separately governed security-operator role with explicit RBAC. A tenant owner or co-admin cannot recover a global Telegram identity.
- Enrollment and changes to the recovery contact must notify existing security channels and be auditable.
- Until these prerequisites and notification delivery are implemented and tested, recovery initiation must remain disabled.

## Recovery state machine

`not_available -> pending_approvals -> protection_period -> ready_for_passkey -> completed`

Terminal or blocking states: `rejected`, `vetoed`, `expired`, `cancelled`, `manual_review`.

1. **Initiate.** A request may be opened from Telegram or the WWW panel. Telegram context may identify a candidate account internally, but the external response is generic. No session is created.
2. **Independent contact approval.** Send a notification/challenge to the pre-registered recovery contact. The contact approves or rejects the specific case using a one-use, case-bound action.
3. **Security operator approval.** A separately authorized security operator reviews the same evidence and records an explicit decision and non-secret rationale. The contact and operator must be different principals.
4. **Protection period.** Only after both approvals, start a 24-hour hold and notify every previously registered security channel. A veto or credible objection blocks completion and moves the case to manual review.
5. **Recovery ceremony.** After the hold expires with no veto, issue a single-use token valid for 10 minutes. It is bound to the account, case, purpose `passkey_recovery_registration`, and the exact recovery ceremony. It cannot create a session.
6. **Finalize.** Verify the new Passkey with required user verification, expected origin and RP ID, and the one-use challenge. In one database transaction, consume the recovery token, mark the case completed, revoke every old Passkey and every active session, and persist the new Passkey. If any step fails, roll back and create no session.
7. **Notify.** Send completion notifications to the independent contact and all available prior security channels. Never include the recovery token or WebAuthn payload.

No independent contact, no eligible operator, unavailable notification channel, ambiguous ownership, or inconsistent evidence means no automatic recovery. The safe alternative is a new identity with access granted by an existing tenant owner; it is not restoration of the old global identity.

## WWW and Telegram parity

The Recovery Security Helper is a review assistant, not an authority. Both interfaces must use the same backend endpoints, state machine, evidence records, RBAC checks, and audit history. They must show the same state, evidence, warnings, missing prerequisites, and recommendations. Actions from either channel must be idempotent and protected against replay.

The helper cannot approve or veto on behalf of a human, alter the credential registry, issue a token, shorten the hold, or bypass fail-closed. Final decisions require an explicit authorized human action with a recorded rationale.

## Optional local AI assistant

An optional local Ollama-backed assistant may summarize redacted diagnostic evidence and explain policy failures. It must remain advisory and isolated behind the backend. It must never receive secrets, contact proofs, tokens, WebAuthn material, or full Telegram initData; it must never execute commands, modify records, approve recovery, or bypass RBAC. Its absence or failure must not affect the deterministic recovery workflow. No Ollama installation, model download, or VPS service change is included in this PR.

## Required persistence and concurrency controls

The eventual implementation needs durable records for recovery cases, independent-contact approvals, operator approvals, vetoes, notification attempts, protection-period timestamps, and one-use recovery tickets. Enforce unique case-bound approvals and ticket hashes. Use PostgreSQL transactions/row locks or conditional updates so that:

- one case cannot be approved twice by the same principal;
- the same person cannot satisfy both approval roles;
- only one active recovery case can proceed for a given account at a time;
- veto, cancellation, expiry, and token consumption race safely with finalization;
- exactly one replacement credential can be registered and all prior credentials/sessions are revoked atomically.

## API contract (proposed)

- `POST /auth/passkeys/recovery`: generic response; may create a case only after verified Telegram context, with no account-existence disclosure.
- `GET /auth/passkeys/recovery/{case_id}`: authenticated, role-filtered case status and evidence summary; never returns secrets.
- `POST /auth/passkeys/recovery/{case_id}/contact-decision`: one-use independent-contact approve/reject action.
- `POST /auth/passkeys/recovery/{case_id}/operator-decision`: RBAC-protected operator decision with required rationale.
- `POST /auth/passkeys/recovery/{case_id}/veto`: authorized veto; blocks finalization.
- `POST /auth/passkeys/recovery/{case_id}/registration/options` and `/verify`: isolated WebAuthn registration ceremony; only an eligible, unexpired, non-vetoed case may proceed.
- No endpoint in this flow may create a session until successful finalization.

Exact route shapes may change during implementation, but the invariants above may not.

## Required acceptance tests

- Generic initiation response for existing/non-existing Telegram identities.
- Telegram initData alone, same phone, username, URL, or PIN cannot approve or complete recovery.
- Missing/unverified contact, missing operator role, same-person dual approval, and unavailable notifications fail closed.
- Contact approval, operator approval, veto, cancellation, expiry, and 24-hour hold transitions.
- No token before both approvals and hold completion; token expires after 10 minutes and is one-use.
- Replay, duplicate approval, parallel approval, parallel finalization, and veto/finalization races.
- No session or cookie before successful replacement Passkey verification.
- Successful finalization atomically revokes all old Passkeys and sessions and stores exactly one new credential.
- Audit and notifications contain no secrets.
- PostgreSQL concurrency tests, full API tests, WWW/Telegram parity tests, and real-device WebAuthn E2E.
- Independent security review before production.

## Release gates

This design does not make the product production-ready. Recovery must remain disabled until the independent-contact enrollment, operator RBAC, notification delivery, database state machine, UI parity, tests, real-device E2E, and independent security review are complete.
