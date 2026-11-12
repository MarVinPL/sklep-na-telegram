# Passkeys w Telegram Mini App

## Decyzja produktowa

Logowanie do Mini App ma opierać się na Passkeys (WebAuthn), a nie na kodzie PIN. PIN nie jest metodą podstawową ani awaryjnym fallbackiem.

Passkey jest poświadczeniem kryptograficznym zarządzanym przez system użytkownika (np. Android Credential Manager / menedżer haseł). Serwer przechowuje wyłącznie identyfikator poświadczenia, klucz publiczny i wymagane metadane — nigdy klucz prywatny.

## Rozdzielenie zaufania

Telegram Mini App dostarcza kontekst Telegrama, który backend musi zweryfikować. Passkey potwierdza posiadanie zarejestrowanego poświadczenia. Te mechanizmy pełnią różne role i nie wolno traktować samego `initData` jako dowodu uwierzytelnienia Passkey ani odwrotnie.

## Docelowy przepływ

### Rejestracja

1. Backend weryfikuje tożsamość i kontekst Telegrama oraz uprawnienie do dodania poświadczenia.
2. Backend generuje losowy, jednorazowy challenge z krótkim terminem ważności i wiąże go z użytkownikiem oraz sesją.
3. Mini App uruchamia WebAuthn `navigator.credentials.create()` z opcjami wygenerowanymi przez backend.
4. Backend weryfikuje odpowiedź, challenge, origin, RP ID, typ ceremonii, flagi wymagane polityką oraz podpis.
5. Backend zapisuje credential ID, klucz publiczny, licznik/obsługę synchronizacji i metadane urządzenia.

### Logowanie

1. Backend wydaje jednorazowy challenge logowania.
2. Mini App uruchamia WebAuthn `navigator.credentials.get()`.
3. Backend weryfikuje podpis i wszystkie parametry odpowiedzi względem zapisanych danych.
4. Po poprawnej weryfikacji backend tworzy/rotuje sesję aplikacyjną.

Challenge nie może być ponownie użyty, a odpowiedzi nie mogą być akceptowane dla innego użytkownika, originu lub RP ID.

## Brak obsługi WebAuthn

Obsługa WebAuthn może zależeć od systemu, przeglądarki i wersji klienta Telegrama. Nie wolno zakładać, że każdy Telegram WebView udostępnia WebAuthn.

Jeżeli funkcja nie jest dostępna:
- pokaż czytelny komunikat;
- zaoferuj otwarcie tej samej Mini App w obsługiwanej, bezpiecznej przeglądarce;
- ewentualne odzyskiwanie konta przeprowadź osobnym, silnie weryfikowanym procesem;
- nie zastępuj Passkey kodem PIN ani słabszym sekretem.

Zgodność trzeba potwierdzić testami na rzeczywistych wersjach Telegram Android, iOS i Desktop. Nie deklarować wsparcia na podstawie samego feature detection.

## Konfiguracja i bezpieczeństwo

- Produkcyjny RP ID musi być jawnie skonfigurowany i zgodny z domeną Mini App.
- Dozwolone originy muszą być jawnie określone per środowisko; bez wildcardów.
- Wymagany HTTPS.
- Challenge losowy, jednorazowy, krótko ważny, przechowywany po stronie serwera i unieważniany po użyciu.
- Wymagaj weryfikacji user presence i user verification zgodnie z polityką bezpieczeństwa.
- Sprawdzaj typ ceremonii, origin, RP ID hash, challenge, podpis i flagi WebAuthn.
- Ochrona przed replay, rate limiting i audyt rejestracji/usunięcia poświadczeń.
- Użytkownik może mieć kilka Passkeys i unieważnić utracone poświadczenie po ponownym potwierdzeniu tożsamości.
- Nie loguj pełnych odpowiedzi WebAuthn ani danych, które mogłyby ujawnić wrażliwe metadane.

### Sesje

Aktualna implementacja przyjmuje politykę **jednej aktywnej sesji aplikacyjnej na użytkownika**. Po poprawnym ponownym uwierzytelnieniu wszystkie wcześniejsze, nieunieważnione sesje użytkownika są unieważniane w tej samej transakcji, w której zapisywana jest nowa sesja. Wylogowanie unieważnia bieżącą sesję po stronie serwera i usuwa cookie po stronie klienta.

Jeśli produkt ma w przyszłości obsługiwać wiele równoległych urządzeń, polityka ta wymaga jawnej zmiany wraz z ekranem zarządzania sesjami i testami unieważniania.

### Walidacja konfiguracji produkcyjnej

Przy `APP_ENV=production` aplikacja odrzuca:
- pusty token bota Telegram;
- SQLite lub nieobsługiwany schemat URL bazy danych (wymagany PostgreSQL);
- RP ID `localhost`;
- origin inny niż HTTPS, zawierający ścieżkę/query/fragment lub host niezgodny z RP ID.

Walidacja konfiguracji nie zastępuje bezpiecznego zarządzania sekretami, konfiguracji reverse proxy, TLS, CORS ani niezależnego przeglądu wdrożenia.

### CSRF, Origin i CORS

Backend stosuje ścisłą listę dozwolonych originów dla API Passkey:
- `CORS_ALLOWED_ORIGINS` zawiera rozdzielone przecinkami, pełne originy (scheme + host + opcjonalny port), bez wildcardów i ścieżek;
- jeśli zmienna jest pusta, używany jest pojedynczy `WEBAUTHN_ORIGIN`;
- w produkcji każdy origin musi używać HTTPS, a jego host musi być równy RP ID lub jego subdomeną;
- CORS dopuszcza credentials, ale wyłącznie dla skonfigurowanych originów, metod GET/POST i nagłówków Content-Type oraz X-Telegram-Init-Data;
- wszystkie żądania modyfikujące stan w routerze Passkey wymagają nagłówka Origin dokładnie równego jednej z wartości allowlisty; brak Origin, `null`, wildcard i obcy origin są odrzucane kodem 403;
- GET/HEAD pozostają metodami bezpiecznymi; preflight OPTIONS obsługuje middleware CORS.

Cookie sesyjne pozostaje HttpOnly, Secure poza development i SameSite=Lax. Topologia wspierana przez tę konfigurację zakłada Mini App i API pod tym samym originem albo pod originami HTTPS w obrębie tej samej domeny RP. Jeśli wdrożenie wymaga różnych domen rejestrowalnych lub cross-site cookies, wymaga osobnego projektu i przeglądu — nie należy osłabiać SameSite ani dodawać wildcardów.

Lokalnie przykładowy `.env.example` dopuszcza `http://localhost:5173` (Vite) i `http://localhost:8000` (API). Produkcja musi podać własne originy. Przed wdrożeniem trzeba potwierdzić, jaki Origin faktycznie wysyłają obsługiwane Telegram WebView na Androidzie/iOS/Desktop; ta lista nie zastępuje testów urządzeń ani niezależnego security review.

### Rate limiting

Wszystkie endpointy routera Passkey mają dwa niezależne limity:
- per bezpośredni adres IP: domyślnie 10 żądań na 60 sekund (`AUTH_RATE_LIMIT_MAX_REQUESTS`);
- per zweryfikowane konto Telegram: domyślnie 6 żądań na 60 sekund (`AUTH_RATE_LIMIT_ACCOUNT_MAX_REQUESTS`).

Okno obu limitów można zmienić przez `AUTH_RATE_LIMIT_WINDOW_SECONDS`. Liczniki są przechowywane w PostgreSQL (SQLite wyłącznie do testów/lokalnego developmentu) i aktualizowane atomowym upsertem, więc są współdzielone między workerami. Konto jest identyfikowane dopiero po poprawnej weryfikacji nagłówka Telegram `initData`; błędne lub brakujące `initData` nadal podlega limitowi IP. Klucz konta jest HMAC z użyciem tokena bota, więc surowy numeryczny Telegram ID nie jest zapisany w tabeli limiterów. Odpowiedź po przekroczeniu limitu to HTTP 429 z nagłówkiem `Retry-After`.

Adres IP pochodzi z połączenia bezpośredniego; nagłówki `X-Forwarded-For` nie są zaufane. W środowisku za reverse proxy należy skonfigurować zaufane proxy i dopiero wtedy rozszerzyć ekstrakcję adresu IP. Limity recovery, test współbieżności limitera na PostgreSQL, sprzątanie wygasłych liczników i audyt retencji pozostają otwarte w Issue #7.

### Handoff do zewnętrznej przeglądarki i ochrona przed enumeracją

Backend udostępnia bazowe endpointy handoff:
- `POST /auth/passkeys/handoff` — weryfikuje Telegram `initData`, wydaje losowy token handoff (32 bajty entropii) i zwraca go Mini App. W bazie zapisywany jest wyłącznie SHA-256 tokenu.
- `POST /auth/passkeys/handoff/authentication/options` — atomowo zużywa token, wiąże challenge WebAuthn z użytkownikiem i zwraca opcje logowania.
- `POST /auth/passkeys/handoff/authentication/verify` — atomowo zużywa challenge, weryfikuje Passkey i dopiero wtedy tworzy sesję aplikacyjną.

Token jest jednorazowy, domyślnie ważny 120 sekund (konfiguracja `PASSKEY_HANDOFF_TTL_SECONDS`, dozwolony zakres 30–300 sekund). Tokenu nie należy umieszczać w query string ani logach. Klient powinien przekazywać go w fragmencie URL (`#ticket=...`), odczytać po stronie przeglądarki i wysłać do endpointu options w treści POST. Fragment nie jest wysyłany w żądaniu HTTP do serwera. Nie przekazywać `initData` do zewnętrznej przeglądarki. Endpointy nie tworzą sesji przed poprawnym WebAuthn.

Endpointy zwykłego logowania i handoff nie zwracają listy `allowCredentials`. Wymuszana jest rejestracja discoverable credential (`residentKey=required`), dzięki czemu liczba i obecność zapisanych poświadczeń nie są ujawniane w odpowiedzi options. Weryfikacja nadal wiąże credential z użytkownikiem wynikającym z Telegrama albo z jednorazowego handoff. Wcześniej zarejestrowane poświadczenia, które nie są discoverable, mogą wymagać ponownej rejestracji; nie należy uznawać migracji istniejących kont za zweryfikowaną bez testu urządzenia.

**Zakres niedokończony:** Mini App nie ma jeszcze ekranu/route odbierającego fragment URL, otwierania przeglądarki zewnętrznej ani end-to-end testu na Telegram Android/iOS/Desktop. Ta zmiana backendu nie oznacza, że handoff jest gotowy do testów użytkownika lub produkcji.

## Testy akceptacyjne

- Rejestracja i logowanie prawidłowym Passkey.
- Niepoprawny podpis, challenge, origin, RP ID i typ ceremonii są odrzucane.
- Ponowne użycie challenge jest odrzucane.
- Poświadczenie unieważnione nie pozwala się zalogować.
- Nie można użyć poświadczenia innego użytkownika.
- Testy integracyjne i end-to-end w obsługiwanych przeglądarkach oraz na rzeczywistych klientach Telegram.
- Brak ścieżki logowania PIN-em.

CI uruchamia testy współbieżnego zużycia challenge i tworzenia użytkownika na usłudze PostgreSQL. Testy te sprawdzają zachowanie blokad/unikalności w PostgreSQL; nie zastępują testów na rzeczywistych klientach Telegram ani niezależnego security review.

## Status implementacji backendu

Gałąź `feat/webauthn-passkey-backend` dodaje backendowy zakres:
- walidację podpisu i świeżości Telegram `initData`;
- generowanie opcji rejestracji i logowania WebAuthn;
- weryfikację odpowiedzi przez `webauthn` (py_webauthn), z wymaganym user verification;
- modele użytkownika, poświadczeń, jednorazowych challenge i sesji;
- challenge powiązany z użytkownikiem, typem operacji i skrótem dokładnego `initData`;
- sesje z losowym tokenem HttpOnly cookie, przechowywanym w DB wyłącznie jako hash;
- wylogowanie i unieważnianie sesji;
- unieważnianie Passkey po zalogowaniu, jeśli użytkownik ma jeszcze co najmniej jedno aktywne poświadczenie;
- migrację Alembic i lokalną konfigurację Compose.

Dodatkowa gałąź hardeningu Issue #9 wprowadza walidację konfiguracji produkcyjnej, rotację aktywnej sesji po ponownym logowaniu, obsługę wyścigu przy tworzeniu użytkownika oraz testy współbieżności uruchamiane na PostgreSQL w CI.

Endpointy:
- `POST /auth/passkeys/registration/options`
- `POST /auth/passkeys/registration/verify`
- `POST /auth/passkeys/authentication/options`
- `POST /auth/passkeys/authentication/verify`
- `POST /auth/passkeys/handoff` (wydanie jednorazowego biletu z Telegram initData)
- `POST /auth/passkeys/handoff/authentication/options` (atomowe zużycie biletu i rozpoczęcie WebAuthn)
- `POST /auth/passkeys/handoff/authentication/verify` (weryfikacja Passkey i utworzenie sesji)
- `GET /auth/passkeys` (lista aktywnych poświadczeń)
- `GET /auth/passkeys/session`
- `POST /auth/passkeys/logout`
- `POST /auth/passkeys/{credential_id}/revoke`

Każdy etap ceremonii wymaga zweryfikowanego nagłówka `X-Telegram-Init-Data`. Logowanie wymaga zarówno aktualnego kontekstu Telegrama, jak i prawidłowego Passkey. PIN nie jest fallbackiem.

To nadal nie jest kompletna funkcja produkcyjna: nie ma jeszcze testów kryptograficznych end-to-end z rzeczywistymi authenticatorami, testów Telegram WebView, pełnego procesu odzyskiwania, limitów per konto ani niezależnego security review. Nie deklarujemy zgodności Telegram Android/iOS/Desktop bez testów na rzeczywistych klientach.
