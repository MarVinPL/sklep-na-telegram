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
  const handoffPage = window.location.pathname.endsWith("/handoff.html");
  const [handoffTicket, setHandoffTicket] = useState<string | null>(() => {
    if (!window.location.pathname.endsWith("/handoff.html")) return null;
    return new URLSearchParams(window.location.hash.slice(1)).get("ticket");
  });
  const [handoffComplete, setHandoffComplete] = useState(false);

  useEffect(() => {
    if (handoffTicket && window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [handoffTicket]);

  const telegramAvailable = isTelegramContextAvailable();
  const passkeyAvailable = supportsPasskeys();

  const refresh = useCallback(async () => {
    if (handoffPage) return;
    if (!telegramAvailable) {
      setSession("signed-out");
      return;
    }
    try {
      await api("/auth/passkeys/session");
      setSession("signed-in");
      const result = await api<{ credentials: PasskeyItem[] }>("/auth/passkeys");
      setCredentials(result.credentials);
    } catch {
      setSession("signed-out");
      setCredentials([]);
    }
  }, [handoffPage, telegramAvailable]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function openExternalBrowser() {
    setBusy(true);
    setMessage("");
    try {
      const ticket = await api<{ handoff_token: string }>("/auth/passkeys/handoff", {
        method: "POST",
      });
      const target = new URL("/handoff.html", window.location.origin);
      target.hash = new URLSearchParams({ ticket: ticket.handoff_token }).toString();
      if (window.Telegram?.WebApp.openLink) {
        window.Telegram.WebApp.openLink(target.toString());
      } else {
        const opened = window.open(target.toString(), "_blank", "noopener,noreferrer");
        if (!opened) throw new Error("Przeglądarka zablokowała otwarcie nowej karty.");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nie udało się otworzyć przeglądarki.");
    } finally {
      setBusy(false);
    }
  }

  async function finishHandoff() {
    if (!handoffTicket) return;
    setBusy(true);
    setMessage("");
    try {
      const options = await api<CeremonyOptions>("/auth/passkeys/handoff/authentication/options", {
        method: "POST",
        body: JSON.stringify({ handoff_token: handoffTicket }),
      });
      setHandoffTicket(null);
      const credential = await getPasskey(options);
      await api("/auth/passkeys/handoff/authentication/verify", {
        method: "POST",
        body: JSON.stringify({ challenge_id: options.challenge_id, credential }),
      });
      setHandoffComplete(true);
      setMessage("Logowanie Passkey zakończone. Możesz wrócić do Telegrama.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nie udało się dokończyć logowania Passkey.");
    } finally {
      setBusy(false);
    }
  }

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
        body: JSON.stringify({
          challenge_id: options.challenge_id,
          credential,
          name: "Passkey",
        }),
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
      setMessage("Passkey został unieważniony.");
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Nie udało się unieważnić Passkey.");
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
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
        <div className="brand-mark">S</div>
        <div>
          <p className="eyebrow">SKLEP NA TELEGRAM</p>
          <h1>Bezpieczne logowanie</h1>
        </div>
      </header>

      {!telegramAvailable && !handoffPage && (
        <section className="notice warning">
          <strong>Brak kontekstu Telegrama</strong>
          <p>Otwórz tę Mini App z poziomu bota Telegram. Nie wpisuj PIN-u ani kodów zastępczych.</p>
        </section>
      )}

      {handoffPage && !handoffTicket && !handoffComplete && (
        <section className="notice warning">
          <strong>Link logowania jest nieprawidłowy lub został już użyty</strong>
          <p>Wróć do Telegrama i rozpocznij logowanie ponownie.</p>
        </section>
      )}

      {handoffPage && handoffTicket && !passkeyAvailable && (
        <section className="notice warning">
          <strong>Ta przeglądarka nie obsługuje WebAuthn</strong>
          <p>Otwórz link w aktualnej przeglądarce obsługującej Passkeys. Nie używaj PIN-u ani kodów zastępczych.</p>
        </section>
      )}

      {handoffPage && handoffTicket && passkeyAvailable && (
        <section className="panel">
          <h2>Dokończ logowanie Passkey</h2>
          <p className="muted">Ten jednorazowy link jest krótkotrwały. Potwierdź tożsamość zapisanym Passkey.</p>
          <button className="button primary" disabled={busy} onClick={() => void finishHandoff()}>
            Potwierdź przez Passkey
          </button>
        </section>
      )}

      {handoffPage && handoffComplete && (
        <section className="notice">
          <strong>Logowanie zakończone</strong>
          <p>Sesja została utworzona. Możesz wrócić do Telegrama.</p>
        </section>
      )}

      {telegramAvailable && !passkeyAvailable && (
        <section className="notice warning">
          <strong>Telegram WebView nie udostępnia WebAuthn</strong>
          <p>Możesz dokończyć logowanie w zewnętrznej przeglądarce obsługującej Passkeys. Link jest jednorazowy i ważny krótko.</p>
          <button className="button primary" disabled={busy} onClick={() => void openExternalBrowser()}>
            Otwórz bezpieczną przeglądarkę
          </button>
        </section>
      )}

      {telegramAvailable && passkeyAvailable && (
        <section className="panel">
          {session === "loading" ? (
            <p className="muted">Sprawdzanie sesji…</p>
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
                <button className="button secondary" disabled={busy} onClick={() => void openExternalBrowser()}>
                  Otwórz w zewnętrznej przeglądarce
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
      {busy && <p className="muted busy">Trwa bezpieczna operacja…</p>}
      <footer>Passkey / WebAuthn · PIN nie jest używany</footer>
    </main>
  );
}
