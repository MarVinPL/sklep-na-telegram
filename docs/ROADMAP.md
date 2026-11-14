# Roadmapa

## Etap 1 — fundament

- [x] Uzgodnienie architektury i stosu technologicznego.
- [x] Wstępny model danych, ról i izolacji tenantów.
- [x] Bezpieczny szablon konfiguracji i lokalna baza PostgreSQL.
- [ ] Przegląd i zatwierdzenie fundamentu.

## Etap 2 — backend i uwierzytelnianie

- [x] Szkielet FastAPI, konfiguracja i health checks.
- [x] SQLAlchemy, Alembic i modele użytkownika/Passkey/sesji.
- [x] Walidacja Telegram Mini App initData.
- [x] Backend Passkey (WebAuthn): rejestracja, logowanie, challenge, sesje i unieważnianie.
- [x] Hardening Origin/CSRF, CORS, rotacja sesji i ochrona współbieżności.
- [x] Rate limiting IP/konto Telegram, PostgreSQL atomic upsert i retencja liczników.
- [x] Pierwszy klient Mini App: rejestracja/logowanie Passkey, zarządzanie kluczami i wylogowanie.
- [x] Jednorazowy handoff do zewnętrznej przeglądarki z redeem sesji w oryginalnym Telegram WebView.
- [ ] Testy E2E na rzeczywistych klientach Telegram Android/iOS/Desktop i fizycznych authenticatorach.
- [ ] Niezależny security review i zatwierdzenie procedury recovery.
- [ ] RBAC i testy izolacji między sklepami.

## Etap 3 — bot i sklep

- [ ] Bot aiogram 3 i bezpieczne webhooki.
- [ ] Mini App: wybór sklepu, katalog i szczegóły produktu.
- [ ] Panel właściciela sklepu.

## Etap 4 — sprzedaż

- [ ] Koszyk i zamówienia.
- [ ] Magazyn, dostawa i rezerwacje usług.
- [ ] Integracje płatności po weryfikacji aktualnych wymagań Telegrama i operatorów.

## Etap 5 — jakość i wdrożenie

- [ ] Testy jednostkowe, integracyjne i end-to-end.
- [ ] Monitoring, audyt, backup i procedury odtwarzania.
- [ ] Dokumentacja instalacji i aktualizacji.
- [ ] Przegląd bezpieczeństwa przed produkcją.
