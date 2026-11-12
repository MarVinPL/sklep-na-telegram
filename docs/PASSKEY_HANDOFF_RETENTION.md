# Retencja rekordów Passkey handoff

Tabela `passkey_handoffs` przechowuje wyłącznie skróty SHA-256 jednorazowych tokenów, ale rekordy nadal wymagają okresowego sprzątania.

- Domyślna retencja: 24 godziny (`PASSKEY_HANDOFF_RETENTION_SECONDS=86400`).
- Dozwolony zakres konfiguracji: 1 godzina–365 dni.
- Rekord wykorzystany jest usuwany dopiero po upływie retencji od `consumed_at`.
- Niewykorzystany rekord jest usuwany dopiero po upływie retencji od `expires_at`.
- Rekordy aktywne oraz niedawno zużyte/wygasłe pozostają w bazie.
- Operacja usuwa wyłącznie rekordy z `passkey_handoffs`; nie dotyka challenge, sesji, poświadczeń ani danych użytkownika.

Uruchomienie ręczne:

```bash
python -m app.security.passkey_handoff_maintenance
```

Moduł nie instaluje crona ani timera systemd. W środowisku docelowym administrator powinien zaplanować uruchamianie np. raz na godzinę i monitorować wynik zadania. Samo dodanie komendy nie oznacza, że automatyczne sprzątanie już działa.
