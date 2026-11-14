# Architektura — wersja 0.1

## Cel

Jeden wspólny backend i jedna baza danych obsługują wiele logicznie odseparowanych sklepów. Telegram Bot jest punktem wejścia, a Telegram Mini App zapewnia bogatszy interfejs katalogu, koszyka i panelu administracyjnego.

## Komponenty docelowe

1. **Bot (aiogram 3)** — komendy, powiadomienia, deep-linki i obsługa webhooków Telegrama.
2. **API (FastAPI)** — logika domenowa, autoryzacja, walidacja, zamówienia i integracje.
3. **Mini App (React + TypeScript)** — katalog, koszyk, konto klienta i interfejs administracyjny.
4. **PostgreSQL** — trwałe dane platformy.
5. **Worker** — zadania asynchroniczne, powiadomienia i obsługa zdarzeń.

## Granice odpowiedzialności

- Frontend nie jest źródłem prawdy o użytkowniku ani uprawnieniach.
- Backend weryfikuje Telegram Mini App `initData` zgodnie z oficjalnym algorytmem Telegrama.
- Bot i Mini App korzystają z tych samych reguł domenowych przez API.
- Każda operacja na danych sklepu musi być ograniczona do aktywnego `shop_id`.
- Koszyk i zamówienie należą do dokładnie jednego sklepu.

## Przepływ żądania

Telegram → Bot lub Mini App → API → uwierzytelnienie i RBAC → tenant context → logika domenowa → PostgreSQL.

## Zasady projektowe

- Modularny monolit na start; mikroserwisy dopiero przy uzasadnionej potrzebie.
- Migracje schematu przez Alembic.
- Idempotencja operacji webhooków i płatności.
- Jawne granice transakcji i audyt operacji administracyjnych.
- Konfiguracja przez zmienne środowiskowe.
