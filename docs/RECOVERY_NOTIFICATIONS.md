# Recovery notifications, veto and protective hold

## Case flow

1. A recovery request is started with verified Telegram initData. Telegram is only a case-start signal; it is not proof of identity and does not create a session.
2. A previously enrolled, verified recovery contact receives a short-lived (15-minute), single-use approval token. A separate veto token is delivered for the protective period.
3. An active security operator records an independent approve/reject decision. The operator must not be the recovery account.
4. The 24-hour hold is eligible only after both approvals. The case-start, contact-approval, operator-approval and hold-start events must all be accepted on both email and Telegram. A delayed or failed critical notice prevents the hold clock from starting.
5. The recovery contact can veto before or during the hold. Veto changes the case to manual_review and blocks automatic progression. There is no override endpoint.
6. The account can cancel its own request before finalization. An unapproved contact token expires after 15 minutes and the worker marks the case expired with notifications.
7. After the hold, the case becomes hold_complete_pending_review. This PR deliberately does not issue a token, create a session, revoke credentials, or activate recovery.

## Durable outbox

- Each event is deduplicated by (event_key, channel) using database-native conflict handling.
- Payloads are encrypted at rest using RECOVERY_CONTACT_ENCRYPTION_KEY. Tokens are never stored in plaintext in the outbox.
- Every delivery attempt is recorded with an outcome and a normalized error code. Active security operators can inspect sanitized event/channel status and attempt history; provider responses, tokens, addresses and message bodies are never exposed.
- Retry is bounded to eight attempts with exponential backoff capped at six hours. Exhaustion marks the row dead and the recovery case notification_blocked.
- Delivery is at-least-once. SMTP/Telegram APIs cannot provide end-to-end exactly-once delivery; an ambiguous provider timeout can result in a duplicate message. Event enqueue is idempotent.
- A dedicated notification-worker Compose service polls the outbox, expires stalled approvals, and detects the end of the 24-hour hold so the completion notice does not depend on a user opening the status screen. It needs the same PostgreSQL database, the encryption key, an operator-managed SMTP relay and a Telegram bot token.

## Channels and fail-closed behavior

The worker sends email through the optional standard-library SMTP adapter and Telegram notices through the Telegram Bot API. Telegram delivery requires that the account has opened the bot chat; otherwise delivery retries and eventually blocks the case. No paid service is provisioned. If either required channel is unavailable, the hold does not start.

A successful provider submission is not proof that the person read the message. The approval token proves mailbox possession only; it does not technically prove that the mailbox is independent from the Telegram account. Enrollment must separately verify that independence, and recovery must remain unavailable if that cannot be established.

## Operational boundaries

- No real SMTP/Telegram messages are sent by CI.
- No vendor account, domain, paid plan or secret is provisioned by this PR.
- Configure SMTP and TELEGRAM_BOT_TOKEN only in deployment secrets. Keep RECOVERY_CONTACT_ENCRYPTION_KEY stable and backed up securely; losing it makes stored contacts and pending encrypted messages unreadable.
- The worker does not activate recovery. A later release still needs a reviewed state machine, UI for the contact approval/veto tokens, real-device E2E and independent security review.
- This PR is stacked on the security-operator and recovery-contact PRs and is not a production deployment.
