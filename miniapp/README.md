# Telegram Mini App — development

React + TypeScript client for the Passkey (WebAuthn) backend.

## Local development

1. Start PostgreSQL and the API from the repository root: `docker compose up -d`.
2. Set a real local `TELEGRAM_BOT_TOKEN`, `CORS_ALLOWED_ORIGINS`, and matching `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` in the root `.env`.
3. Run `npm install` and `npm run dev` from this directory.
4. Open the Mini App through the Telegram bot context. Vite proxies `/auth` requests to `http://127.0.0.1:8000`.

WebAuthn requires a secure context (HTTPS or localhost), an exact RP ID/origin match, and an authenticator available to the browser. The UI intentionally has no PIN fallback.

## Passkey and external-browser handoff

The Mini App supports direct Passkey registration/login and a one-time external-browser handoff when WebAuthn is unavailable inside Telegram WebView. The handoff ticket is 256-bit random, stored server-side only as a hash, bound to the original Telegram `initData` context and short-lived. It is passed in a URL fragment (never query), removed from browser history immediately, and sent to the backend only in POST bodies.

The external browser verifies the Passkey but does not receive an application session. The original Telegram Mini App redeems the verified ticket with the original `initData`; only then is the HttpOnly session cookie issued in the Telegram WebView context. If the original Mini App is closed and loses the in-memory ticket/context, the user must restart the handoff.

## Current limitations

- This is an initial authentication client, not a production-ready storefront.
- Telegram WebView support and `Telegram.WebApp.openLink` behavior must be validated on real Android, iOS and Desktop clients.
- Physical authenticator E2E tests, account recovery, and independent security review remain outstanding.
