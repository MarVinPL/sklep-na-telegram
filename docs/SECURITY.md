# Bezpieczeństwo i izolacja tenantów

## Tożsamość Telegram

- Weryfikuj podpis i świeżość `initData` po stronie serwera według dokumentacji Telegrama.
- Nie ufaj danym użytkownika przekazanym wyłącznie przez frontend.
- Token bota i sekrety webhooków przechowuj poza repozytorium.
- Nie loguj tokenów, pełnych danych uwierzytelniających ani wrażliwych danych klientów.

## Izolacja sklepów

- Ustalaj tenant context po stronie backendu na podstawie uwierzytelnionej sesji i członkostwa.
- Nigdy nie przyjmuj `shop_id` z klienta jako wystarczającego dowodu dostępu.
- Każde zapytanie i operacja zapisu musi być ograniczona do autoryzowanego sklepu.
- Testuj próby odczytu, modyfikacji i łączenia rekordów między sklepami.
- Rozważ PostgreSQL Row-Level Security jako dodatkową warstwę ochrony, nie zamiennik autoryzacji aplikacyjnej.

## Role

- **Platform Owner** — administracja całej platformy.
- **Shop Owner** — pełna administracja własnym sklepem.
- **Shop Admin** — zarządzanie sklepem zgodnie z nadanymi uprawnieniami.
- **Shop Operator** — realizacja zamówień i obsługa operacyjna.
- **Customer** — własny profil, koszyk i zamówienia.

## Pozostałe zabezpieczenia

- RBAC i zasada najmniejszych uprawnień.
- Weryfikacja podpisów webhooków, idempotencja i ochrona przed replay.
- Rate limiting, walidacja wejścia i bezpieczne nagłówki.
- Audyt działań administracyjnych.
- Kopie zapasowe szyfrowane i regularnie testowane.
- Brak sekretów w repozytorium, issue, fixture'ach i logach.

Przed obsługą prawdziwych płatności lub danych klientów wymagane są testy bezpieczeństwa i przegląd prawny integracji.
