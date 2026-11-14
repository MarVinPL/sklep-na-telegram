# Telegram Mini App — development

React + TypeScript client for the Passkey (WebAuthn) endpoints in the FastAPI backend.

## Local development

1. Start PostgreSQL and the API from the repository root: `docker compose up -d`.
2. Set a local `TELEGRAM_BOT_TOKEN` and matching `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` in the root `.env`.
3. Run `npm install` and `npm run dev` from this directory.
4. Open the Mini App through a Telegram bot configured with the local HTTPS development URL.

Vite proxies `/auth` and `/healthz` to `http://127.0.0.1:8000`. In a deployed same-origin topology, the frontend uses relative API paths. The API must receive the exact Telegram `initData` in `X-Telegram-Init-Data`.

WebAuthn requires a secure context (HTTPS or localhost), a matching RP ID/origin, and an authenticator available to the browser. The UI intentionally has no PIN fallback.

## Current scope and limitations

- Direct Passkey registration, authentication, credential listing/revocation, and logout.
- External-browser handoff is deliberately not included in this change; it depends on the separate backend handoff and hardening work.
- The UI is an initial authentication client, not a production-ready storefront.
- Telegram WebView support must be validated on real Android, iOS, and Desktop clients.
- Physical authenticator E2E tests, account recovery, and independent security review remain outstanding.
