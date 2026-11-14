# Independent recovery contact

## Status

Issue #30 implements only initial enrollment and verification of an independent email contact. It does not enable account recovery and does not implement contact replacement. Recovery remains unavailable until operator RBAC, notification/veto, the recovery state machine, real-device tests, and independent security review are complete.

## Requirements

- Enrollment requires an authenticated application session bound to the same verified Telegram identity and a fresh WebAuthn assertion with user verification.
- At least two active Passkeys are required before enrollment.
- The email address is encrypted at rest with Fernet. A separate HMAC digest supports uniqueness checks without storing plaintext.
- The encryption key is configured outside source control using RECOVERY_CONTACT_ENCRYPTION_KEY. Generate a Fernet key with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" and store it only in the deployment secret environment.
- A random one-use verification token is stored only as SHA-256 hash and sent using the optional operator-configured SMTP transport. It expires after 15 minutes.
- SMTP submission is not proof of mailbox ownership; only confirmation with the one-use token marks the contact verified.
- The mailbox must be independently controlled and not merely another identifier or recovery channel for the Telegram account. SMS-only contacts are not accepted.
- The API reveals only configured/verified status, never the email address or token.

## Deliberate limitations

- The initial version does not allow replacing a verified contact. Replacement requires the notification and protective-period mechanism from Issue #32, so it fails closed instead of bypassing that dependency.
- There is no recovery-case initiation or recovery approval in this feature.
- No provider is provisioned. Local development can use a free self-hosted SMTP sink such as Mailpit; production SMTP remains operator-managed and optional.
- The key must be backed up securely by the operator. Losing it makes stored contact addresses unrecoverable.
