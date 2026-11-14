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

## Testy akceptacyjne

- Rejestracja i logowanie prawidłowym Passkey.
- Niepoprawny podpis, challenge, origin, RP ID i typ ceremonii są odrzucane.
- Ponowne użycie challenge jest odrzucane.
- Poświadczenie unieważnione nie pozwala się zalogować.
- Nie można użyć poświadczenia innego użytkownika.
- Testy integracyjne i end-to-end w obsługiwanych przeglądarkach oraz na rzeczywistych klientach Telegram.
- Brak ścieżki logowania PIN-em.

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

Endpointy:
- `POST /auth/passkeys/registration/options`
- `POST /auth/passkeys/registration/verify`
- `POST /auth/passkeys/authentication/options`
- `POST /auth/passkeys/authentication/verify`
- `GET /auth/passkeys` (lista aktywnych poświadczeń)
- `GET /auth/passkeys/session`
- `POST /auth/passkeys/logout`
- `POST /auth/passkeys/{credential_id}/revoke`

Każdy etap ceremonii wymaga zweryfikowanego nagłówka `X-Telegram-Init-Data`. Logowanie wymaga zarówno aktualnego kontekstu Telegrama, jak i prawidłowego Passkey. PIN nie jest fallbackiem.

To nadal nie jest kompletna funkcja produkcyjna: nie ma jeszcze frontendowej Mini App wywołującej `navigator.credentials.create/get`, testów kryptograficznych end-to-end z rzeczywistymi authenticatorami, testów Telegram WebView, pełnego procesu odzyskiwania ani przeglądu bezpieczeństwa. Rate limiting musi zostać dodany na warstwie API/gateway przed wystawieniem publicznym. Nie deklarujemy zgodności Telegram Android/iOS/Desktop bez testów na rzeczywistych klientach.

Lokalnie ustaw `TELEGRAM_BOT_TOKEN`, `WEBAUTHN_RP_ID` i `WEBAUTHN_ORIGIN`. W środowisku produkcyjnym wymagane są HTTPS oraz dokładne dopasowanie RP ID i originu.


## Hardening CSRF, Origin i CORS

Wszystkie mutujące endpointy routera Passkey wymagają nagłówka `Origin` dokładnie równego jednej z wartości `CORS_ALLOWED_ORIGINS`. Brak Origin, `null`, wildcard lub obcy origin są odrzucane kodem 403. Metody GET/HEAD i preflight OPTIONS nie wymagają tego nagłówka.

- `CORS_ALLOWED_ORIGINS` przyjmuje rozdzielone przecinkami, pełne originy (scheme + host + opcjonalny port), bez ścieżek, query, fragmentów i wildcardów.
- Gdy lista jest pusta, używany jest `WEBAUTHN_ORIGIN`.
- Middleware CORS dopuszcza credentials wyłącznie dla skonfigurowanych originów, metod GET/POST/OPTIONS i nagłówków Content-Type oraz X-Telegram-Init-Data.
- W produkcji originy muszą używać HTTPS i należeć do domeny RP ID lub jej subdomen.
- Cookie sesyjne pozostaje HttpOnly, Secure poza development i SameSite=Lax.

Lokalny przykład dopuszcza `http://localhost:5173` (Vite) oraz `http://localhost:8000` (API). Nie dodawaj wildcardów ani originów Telegrama na ślepo — przed produkcją należy potwierdzić rzeczywisty Origin wysyłany przez docelowe Telegram WebView.

## Sesje i współbieżność

Polityka backendu to jedna aktywna sesja aplikacyjna na użytkownika. Po poprawnym logowaniu wcześniejsze aktywne sesje są unieważniane w tej samej transakcji, w której powstaje nowa sesja. Unieważnienie Passkey unieważnia również sesje użytkownika. Tworzenie użytkownika obsługuje wyścig równoległych pierwszych żądań przez ponowne odczytanie rekordu po konflikcie unikalności Telegram ID.

CI uruchamia dodatkowo testy współbieżnego zużycia tego samego challenge i tworzenia użytkownika na PostgreSQL 16. Testy SQLite nie zastępują tych testów, ponieważ SQLite nie zapewnia semantyki blokad wierszy PostgreSQL.


## Pierwszy klient Mini App

Frontend React + TypeScript w katalogu `miniapp/` obsługuje bezpośrednie endpointy backendu:
- rejestrację przez `navigator.credentials.create()`;
- logowanie przez `navigator.credentials.get()`;
- listę i unieważnianie Passkeys;
- wylogowanie.

Klient przekazuje Telegram `initData` wyłącznie w nagłówku `X-Telegram-Init-Data`, a cookie sesyjne przez `credentials: include`. Nie zapisuje tokenów sesyjnych w JavaScript i nie oferuje PIN-u.

Handoff do zewnętrznej przeglądarki celowo nie jest częścią tego PR. Wymaga osobnych endpointów backendowych, atomowego zużycia biletów i testów na rzeczywistych klientach Telegram. Nie należy pokazywać przycisku handoff, dopóki zależny backend nie zostanie scalony i zweryfikowany.


## Rate limiting endpointów Passkey

Każdy endpoint Passkey ma dwa niezależne, trwałe limity:
- per bezpośredni adres IP i ścieżka endpointu: domyślnie 10 żądań na 60 sekund;
- per zweryfikowane konto Telegram i ścieżka endpointu: domyślnie 6 żądań na 60 sekund.

Wartości można zmienić przez `AUTH_RATE_LIMIT_MAX_REQUESTS`, `AUTH_RATE_LIMIT_ACCOUNT_MAX_REQUESTS` i `AUTH_RATE_LIMIT_WINDOW_SECONDS`. Liczniki są przechowywane w PostgreSQL i aktualizowane atomowym upsertem, więc współdzielą stan między workerami. SQLite jest obsługiwane wyłącznie dla lokalnych testów.

Dla konta używany jest HMAC z tokenem bota, a nie surowy Telegram ID. Niepoprawne lub brakujące `initData` nadal podlega limitowi IP; limit konta jest naliczany dopiero po poprawnej weryfikacji Telegrama. Przekroczenie limitu zwraca HTTP 429 z nagłówkiem `Retry-After`.

Adres IP pochodzi wyłącznie z bezpośredniego połączenia. `X-Forwarded-For` nie jest zaufany, dopóki nie zostanie skonfigurowana jawna lista zaufanych reverse proxy. Limity recovery pozostają osobnym zadaniem. Wygasłe buckety można usuwać poleceniem `python -m app.security.rate_limit_maintenance`; domyślna retencja wynosi 24 godziny i można ją zmienić przez `AUTH_RATE_LIMIT_RETENTION_SECONDS` (1 godzina–365 dni). Repozytorium nie instaluje harmonogramu — operator powinien uruchamiać polecenie cyklicznie (np. raz na godzinę) przez cron lub systemd timer.


## Jednorazowy handoff do zewnętrznej przeglądarki

Handoff jest związany z konkretnym użytkownikiem, celem `authentication` i skrótem dokładnego Telegram `initData` z żądania wydającego bilet. Surowy token ma 256 bitów entropii; w bazie przechowywany jest wyłącznie jego SHA-256. Domyślny TTL to 120 sekund, konfigurowalny w zakresie 30–300 sekund.

Przepływ jest dwuetapowy, aby nie zakładać współdzielenia cookie pomiędzy Telegram WebView a zewnętrzną przeglądarką:

1. Telegram Mini App żąda biletu i otwiera `handoff.html#ticket=...`. Token trafia do fragmentu URL, nigdy do query string; strona zewnętrzna odczytuje go i natychmiast usuwa fragment przez `history.replaceState`.
2. Zewnętrzna przeglądarka atomowo zużywa bilet, pobiera discoverable WebAuthn challenge i potwierdza Passkey. Nie wysyła Telegram `initData` i nie otrzymuje sesji aplikacyjnej.
3. Po poprawnym WebAuthn backend oznacza bilet jako zweryfikowany. Użytkownik wraca do oryginalnej Mini App i wybiera „Sprawdź status logowania”.
4. Oryginalna Mini App wysyła token wraz z oryginalnym Telegram `initData` do endpointu redeem. Backend porównuje hash kontekstu, użytkownika i cel, atomowo zużywa redemption i dopiero wtedy ustawia cookie HttpOnly w Telegram WebView.

Dzięki temu sesja powstaje dopiero po poprawnym Passkey i w kontekście, w którym Mini App będzie z niej korzystać. Jeśli oryginalna Mini App zostanie zamknięta i utraci stan tokenu lub Telegram wyda inne `initData`, użytkownik musi rozpocząć handoff ponownie; nie należy osłabiać wiązania kontekstu.

Bilety i challenge są jednorazowe i atomowo zużywane. Odpowiedzi dla braku konta/Passkey nie ujawniają listy credential IDs ani ich liczby; używane są discoverable credentials (`residentKey=required`). Weryfikacja nie tworzy sesji w zewnętrznej przeglądarce. Rate limiting obejmuje wydawanie, options, verify i redeem.

Logi audytowe zawierają wyłącznie nazwę zdarzenia, wewnętrzny user ID i niesekretny powód odrzucenia. Nie logują tokenu, jego hasha, Telegram `initData`, credential ID ani odpowiedzi WebAuthn.

**Pozostałe bramki przed produkcją:** testy end-to-end na rzeczywistych klientach Telegram Android/iOS/Desktop, testy z fizycznymi authenticatorami, sprawdzenie zachowania `Telegram.WebApp.openLink` i niezależny security review.
