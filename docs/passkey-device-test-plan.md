# Plan testów Passkey na rzeczywistych urządzeniach

## Cel i status

Ten dokument opisuje testy wymagane przed uznaniem logowania Passkey w Telegram Mini App za gotowe. Testy muszą być wykonane na rzeczywistych klientach Telegram i authenticatorach. Zielone CI, testy jednostkowe oraz build frontendu nie zastępują tych prób.

**Status:** plan przygotowany; brak potwierdzonych wyników testów na urządzeniach fizycznych.

## Warunki wstępne

- [ ] PR #3, PR #4 i PR #6 są dostępne w jednym środowisku testowym po kontrolowanym scaleniu zgodnie z zależnościami.
- [ ] Środowisko testowe działa wyłącznie przez HTTPS.
- [ ] `WEBAUTHN_RP_ID` odpowiada domenie środowiska, a `WEBAUTHN_ORIGIN` dokładnemu originowi Mini App.
- [ ] Bot i Mini App wskazują na to samo środowisko testowe.
- [ ] Używane są testowe konta Telegram i testowe dane; brak prawdziwych sekretów w logach.
- [ ] Włączone są bezpieczne logi diagnostyczne bez surowego initData, tokenów, challenge ani danych credential.

## Macierz klientów

Każdy wiersz należy wykonać osobno i zapisać wersję systemu, wersję Telegrama, przeglądarkę/systemowy provider Passkey oraz wynik.

| Platforma | Klient | Rejestracja | Logowanie | Uwagi |
|---|---|---:|---:|---|
| Android | Telegram — Mini App / WebView | ⬜ | ⬜ | Główna ścieżka do sprawdzenia |
| Android | Chrome po otwarciu bezpiecznego handoffu | ⬜ | ⬜ | Sprawdzić powrót do właściwej operacji |
| iOS | Telegram — Mini App / WebView | ⬜ | ⬜ | Sprawdzić zachowanie WebAuthn w aktualnym wydaniu |
| iOS | Safari po handoffie | ⬜ | ⬜ | Sprawdzić powiązanie operacji i sesji |
| Desktop | Telegram Desktop | ⬜ | ⬜ | Zależne od systemu i dostępnego authenticatora |
| Desktop | Obsługiwana przeglądarka | ⬜ | ⬜ | Sprawdzić platformowy i zewnętrzny authenticator |

## Scenariusze pozytywne

- [ ] Pierwsza rejestracja Passkey po prawidłowej weryfikacji Telegram initData.
- [ ] Logowanie istniejącym Passkey po ponownym uruchomieniu Mini App.
- [ ] Dodanie drugiego Passkey do tego samego konta.
- [ ] Wyświetlenie listy zarejestrowanych Passkeys bez ujawniania materiału prywatnego.
- [ ] Unieważnienie wybranego Passkey i potwierdzenie, że nie może już uwierzytelnić użytkownika.
- [ ] Poprawne utworzenie sesji po udanej ceremonii WebAuthn oraz poprawne wylogowanie.

## Scenariusze negatywne i bezpieczeństwa

- [ ] Odmowa lub anulowanie promptu authenticatora nie tworzy sesji.
- [ ] Nieprawidłowy lub wygasły challenge jest odrzucany.
- [ ] Ponowne użycie challenge jest odrzucane, również przy dwóch równoległych żądaniach.
- [ ] Nieprawidłowy origin lub RP ID jest odrzucany.
- [ ] Credential innego użytkownika nie uwierzytelnia bieżącego konta.
- [ ] Unieważniony credential nie może się zalogować.
- [ ] Brak WebAuthn nie uruchamia PIN-u ani słabszego fallbacku.
- [ ] Błędne, przeterminowane lub ponownie użyte dane handoffu nie tworzą sesji.
- [ ] Surowe Telegram initData i sekrety nie pojawiają się w URL ani logach.

## Rejestrowanie wyniku

Dla każdego przypadku zapisać:

- datę i środowisko testowe;
- platformę, model urządzenia i wersję systemu;
- wersję Telegrama i nazwę/wersję przeglądarki;
- typ authenticatora (platformowy lub zewnętrzny; bez identyfikatorów sekretów);
- kroki wykonane i wynik: PASS / FAIL / BLOCKED;
- krótki opis błędu oraz niesekretne identyfikatory korelacyjne logów.

Nie dołączać zrzutów ekranu zawierających QR, tokeny, initData, challenge, dane osobowe ani inne sekrety.

## Kryteria zakończenia

- Wszystkie platformy uznane za wspierane mają udokumentowane wyniki rejestracji i logowania.
- Wszystkie scenariusze negatywne przechodzą.
- Nie ma ścieżki PIN.
- Ograniczenia niewspieranych klientów są jawnie opisane w Mini App i dokumentacji.
- Wyniki zostały dodane do Issue #2, a wszystkie problemy bezpieczeństwa do Issue #7.
- Przed produkcją wykonano niezależny przegląd bezpieczeństwa.

**Ważne:** nie oznaczać platformy jako wspieranej na podstawie samego builda lub testów symulowanych. Nie wykonywać testów na produkcyjnych kontach ani danych.
