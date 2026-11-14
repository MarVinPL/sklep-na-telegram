import { useCallback, useEffect, useState } from "react";
import { api, type CeremonyOptions, type PasskeyItem } from "./lib/api";
import { isTelegramContextAvailable } from "./lib/telegram";
import { createPasskey, getPasskey, supportsPasskeys } from "./lib/webauthn";

type SessionState = "loading" | "signed-out" | "signed-in";

export default function App() {
  const [session, setSession] = useState<SessionState>("loading");
  const [credentials, setCredentials] = useState<PasskeyItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const telegramAvailable = isTelegramContextAvailable();
  const passkeyAvailable = supportsPasskeys();

  const refresh = useCallback(async () => {
    if (!telegramAvailable) {
      setSession("signed-out");
      setCredentials([]);
      return;
    }
    try {
      await api("/auth/passkeys/session");
      const result = await api<{ credentials: PasskeyItem[] }>("/auth/passkeys");
      setCredentials(result.credentials);
      setSession("signed-in");
    } catch {
      setSession("signed-out");
      setCredentials([]);
    }
  }, [telegramAvailable]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function registerPasskey() {
    setBusy(true);
    setMessage("");
    try {
      const options = await api<CeremonyOptions>("/auth/passkeys/registration/options", {
        method: "POST",
      });
      const credential = await createPasskey(options);
      await api("/auth/passkeys/registration/verify", {
        method: "POST",
        body: JSON.stringify({ challenge_id: options.challenge_id, credential, name: "Passkey" }),
      });
      setMessage("Passkey został zarejestrowany. Teraz zaloguj się tym Passkey.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nie udało się zarejestrować Passkey.");
    } finally {
      setBusy(false);
    }
  }

  async function login() {
    setBusy(true);
    setMessage("");
    try {
      const options = await api<CeremonyOptions>("/auth/passkeys/authentication/options", {
        method: "POST",
      });
      const credential = await getPasskey(options);
      await api("/auth/passkeys/authentication/verify", {
        method: "POST",
        body: JSON.stringify({ challenge_id: options.challenge_id, credential }),
      });
      setMessage("Logowanie Passkey zakończone powodzeniem.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Logowanie Passkey nie powiodło się.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(credentialId: string) {
    setBusy(true);
    setMessage("");
    try {
      await api(`/auth/passkeys/${encodeURIComponent(credentialId)}/revoke`, {
        method: "POST",
      });
      setMessage("Passkey został unieważniony. Zaloguj się ponownie.");
      setSession("signed-out");
      setCredentials([]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nie udało się unieważnić Passkey.");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    setMessage("");
    try {
      await api("/auth/passkeys/logout", { method: "POST" });
      setSession("signed-out");
      setCredentials([]);
      setMessage("Wylogowano.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nie udało się wylogować.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand-mark" aria-hidden="true">S</div>
        <div>
          <p className="eyebrow">SKLEP NA TELEGRAM</p>
          <h1>Bezpieczne logowanie</h1>
        </div>
      </header>

      {!telegramAvailable && (
        <section className="notice warning" role="alert">
          <strong>Brak kontekstu Telegrama</strong>
          <p>Otwórz tę Mini App z poziomu bota Telegram. Nie wpisuj PIN-u ani kodów zastępczych.</p>
        </section>
      )}

      {telegramAvailable && !passkeyAvailable && (
        <section className="notice warning" role="alert">
          <strong>WebAuthn niedostępny w tym środowisku</strong>
          <p>
            Otwórz Mini App w obsługiwanej przeglądarce i bezpiecznym kontekście HTTPS.
            Logowanie PIN-em nie jest dostępne.
          </p>
        </section>
      )}

      {telegramAvailable && passkeyAvailable && (
        <section className="panel">
          {session === "loading" ? (
            <p className="muted" role="status">Sprawdzanie sesji…</p>
          ) : session === "signed-in" ? (
            <>
              <div className="status-line"><span className="dot" /> Zalogowano przez Passkey</div>
              <h2>Twoje Passkeys</h2>
              {credentials.length === 0 ? (
                <p className="muted">Brak aktywnych poświadczeń.</p>
              ) : (
                <ul className="credential-list">
                  {credentials.map((item) => (
                    <li key={item.credential_id}>
                      <div>
                        <strong>{item.name || "Passkey"}</strong>
                        <small>Dodano: {new Date(item.created_at).toLocaleDateString("pl-PL")}</small>
                      </div>
                      <button
                        className="button subtle"
                        disabled={busy || credentials.length <= 1}
                        onClick={() => void revoke(item.credential_id)}
                      >
                        Unieważnij
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="actions">
                <button className="button secondary" disabled={busy} onClick={() => void registerPasskey()}>
                  Dodaj Passkey
                </button>
                <button className="button subtle" disabled={busy} onClick={() => void logout()}>
                  Wyloguj
                </button>
              </div>
            </>
          ) : (
            <>
              <h2>Zaloguj się bez PIN-u</h2>
              <p className="muted">Użyj klucza dostępu zapisanego w urządzeniu lub menedżerze haseł.</p>
              <div className="actions vertical">
                <button className="button primary" disabled={busy} onClick={() => void login()}>
                  Zaloguj przez Passkey
                </button>
                <button className="button secondary" disabled={busy} onClick={() => void registerPasskey()}>
                  Zarejestruj pierwszy Passkey
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {message && <p className="feedback" role="status">{message}</p>}
      {busy && <p className="muted busy" role="status">Trwa bezpieczna operacja…</p>}
      <footer>Passkey / WebAuthn · PIN nie jest używany</footer>
    </main>
  );
}
