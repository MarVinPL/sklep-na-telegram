# Sklep na Telegram

Uniwersalna, otwartoźródłowa platforma sklepowa działająca w Telegramie. Jeden backend obsługuje wiele niezależnych sklepów (multi-tenant), a klienci i administratorzy korzystają z bota Telegram oraz Telegram Mini App.

> **Status: wczesny development.** Dostępne są fundamenty, API FastAPI, PostgreSQL i backendowe endpointy Passkey (WebAuthn). Nie ma jeszcze Mini App, bota, katalogu, koszyka ani procesu płatności. To nie jest wdrożenie produkcyjne.

## Założenia

- Telegram jest jedynym interfejsem użytkownika.
- Obsługa produktów fizycznych, cyfrowych i usług.
- Wiele sklepów w jednej instalacji, z wymuszoną izolacją danych.
- Osobne role platformy, właściciela sklepu, administratora, operatora i klienta.
- Darmowy lokalny tryb developerski; brak wymaganych płatnych usług.
- Sekrety wyłącznie w lokalnym `.env` lub menedżerze sekretów — nigdy w repozytorium.

## Planowany stos

- Python 3.12+, FastAPI i aiogram 3
- PostgreSQL, SQLAlchemy 2 i Alembic
- React + TypeScript dla Telegram Mini App
- pytest oraz Playwright
- Docker Compose

## Szybki start środowiska

1. Skopiuj `.env.example` do `.env`.
2. Uzupełnij lokalne wartości konfiguracyjne.
3. Uruchom `docker compose up -d`.

Docker Compose uruchamia lokalnie PostgreSQL i API; migracje Alembic wykonują się przy starcie kontenera API. Ustaw prawdziwy lokalny `TELEGRAM_BOT_TOKEN` oraz dokładne `WEBAUTHN_RP_ID` i `WEBAUTHN_ORIGIN`, zanim przetestujesz endpointy Passkey. Domyślne wartości RP/origin służą wyłącznie lokalnemu developmentowi. Bot i Mini App nie są jeszcze zaimplementowane, więc sam backend nie jest gotowym sklepem.

## Dokumentacja

- [Architektura](docs/ARCHITECTURE.md)
- [Model danych](docs/DATA_MODEL.md)
- [Bezpieczeństwo i izolacja tenantów](docs/SECURITY.md)
- [Plan rozwoju](docs/ROADMAP.md)
- [Logowanie Passkey do Mini App](docs/PASSKEY_AUTH.md)

## Płatności

Integracja płatności nie jest jeszcze zaimplementowana. Przed jej dodaniem trzeba zweryfikować aktualne zasady Telegram Stars dla dóbr i usług cyfrowych oraz wymagania operatorów płatności dla pozostałych transakcji.

## Wkład w projekt

Zmiany proponuj przez Pull Request do `main`. Nie umieszczaj tokenów, danych klientów ani prawdziwych danych płatniczych w issue, commitach i logach.

## Licencja

Licencja zostanie wybrana po sprawdzeniu licencji wszystkich bezpośrednich zależności i dodaniu właściwych informacji o prawach autorskich.
