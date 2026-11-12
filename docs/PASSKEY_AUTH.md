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

## Status

To wymaganie architektoniczne. Implementacja backendu WebAuthn, modelu danych, ekranów Mini App, procesu odzyskiwania i testów urządzeń jest osobnym zadaniem: [Issue #2](https://github.com/MarVinPL/sklep-na-telegram/issues/2).
