# Sklep na Telegram

Uniwersalna, otwartoźródłowa platforma sklepowa działająca w Telegramie. Jeden backend obsługuje wiele niezależnych sklepów (multi-tenant), a klienci i administratorzy korzystają z bota Telegram oraz Telegram Mini App.

> **Status: wczesny development.** Dostępne są fundamenty, API FastAPI, PostgreSQL, backend Passkey (WebAuthn), pierwszy frontend Mini App oraz podstawowy handoff do zewnętrznej przeglądarki. Nie ma jeszcze bota, katalogu, koszyka ani procesu płatności. To nie jest wdrożenie produkcyjne.

## Założenia

- Jeden backend dla wielu sklepów Telegram.
- Bot Telegram i Mini App korzystają z tego samego API.
- Uwierzytelnianie użytkownika przez Passkey (WebAuthn); PIN nie jest fallbackiem.
- Sekrety przechowywane wyłącznie w lokalnym `.env` lub zewnętrznym managerze sekretów.

## Lokalny backend

1. Skopiuj `.env.example` do `.env`.
2. Uzupełnij lokalne wartości konfiguracyjne, w tym silne `POSTGRES_PASSWORD`.
3. Uruchom `docker compose up -d`.

Docker Compose uruchamia lokalnie PostgreSQL i API; migracje Alembic wykonują się przy starcie kontenera API. W produkcji wymagane są jawne ustawienia PostgreSQL, token Telegram i HTTPS origin zgodny z RP ID. Domyślne wartości RP/origin służą wyłącznie lokalnemu developmentowi.

## Mini App (development)

Frontend React + TypeScript znajduje się w `miniapp/`. Uruchom backend (`docker compose up -d`), a następnie w drugim terminalu wykonaj `cd miniapp && npm install && npm run dev`. Vite przekazuje ścieżki `/auth` do lokalnego API FastAPI. WebAuthn wymaga bezpiecznego kontekstu (HTTPS lub localhost), zgodnego RP ID/origin i rzeczywistego kontekstu Telegram Mini App.

Aktualny klient obsługuje bezpośrednią rejestrację, logowanie, listowanie/unieważnianie Passkeys, wylogowanie oraz jednorazowy handoff do zewnętrznej przeglądarki. Sesja jest tworzona w oryginalnym Telegram WebView dopiero po potwierdzeniu Passkey i redeem biletu. Nie ma fallbacku PIN.

## Dokumentacja

- [Architektura](docs/ARCHITECTURE.md)
- [Model danych](docs/DATA_MODEL.md)
- [Bezpieczeństwo](docs/SECURITY.md)
- [Autoryzacja Passkey](docs/PASSKEY_AUTH.md)
- [Plan rozwoju](docs/ROADMAP.md)
