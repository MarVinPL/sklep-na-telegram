# Telegram Mini App — development

React + TypeScript client for the Passkey (WebAuthn) backend.

## Local development

1. Start the API and PostgreSQL from the repository root: `docker compose up -d`.
2. Set a real local `TELEGRAM_BOT_TOKEN` and matching `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` in the root `.env`.
3. Run `npm install` and `npm run dev` from this directory.
4. Open the Mini App through the Telegram bot context. Vite proxies `/auth` requests to `http://127.0.0.1:8000`.

WebAuthn requires a secure context (HTTPS or localhost) and an exact RP ID/origin match. A non-Telegram browser without signed Telegram `initData` cannot authenticate. The UI intentionally has no PIN fallback.

## Current limitations

- This is an initial client, not a production-ready storefront.
- Telegram WebView support must be validated on real Android, iOS and Desktop clients.
- External-browser Passkey authentication handoff is implemented in the client; real Telegram/device validation is still outstanding.
- Account recovery is not implemented and has no PIN fallback.
- End-to-end tests with physical authenticators and full recovery flow remain outstanding.
