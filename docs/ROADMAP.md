# Roadmapa

## Etap 1 — fundament (bieżący PR)

- [x] Uzgodnienie architektury i stosu technologicznego.
- [x] Wstępny model danych, ról i izolacji tenantów.
- [x] Bezpieczny szablon konfiguracji i lokalna baza PostgreSQL.
- [ ] Przegląd i zatwierdzenie fundamentu.

## Etap 2 — backend

- [ ] Szkielet FastAPI, konfiguracja i health checks.
- [ ] SQLAlchemy, Alembic i modele User/Shop/Membership.
- [ ] Walidacja Telegram Mini App initData.
- [ ] Passkey (WebAuthn) jako metoda logowania do Mini App — bez fallbacku PIN.
- [ ] RBAC i testy izolacji między sklepami.

## Etap 3 — bot i Mini App

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
