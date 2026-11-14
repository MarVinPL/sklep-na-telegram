import { getTelegramInitData } from "./telegram";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export interface CeremonyOptions {
  challenge_id: string;
  publicKey: Record<string, unknown>;
}

export interface PasskeyItem {
  credential_id: string;
  name: string | null;
  created_at: string;
  device_type: string | null;
  backed_up: boolean;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const initData = getTelegramInitData();
  if (initData) headers.set("X-Telegram-Init-Data", initData);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      typeof payload.detail === "string" ? payload.detail : `Błąd API (${response.status})`;
    throw new Error(message);
  }
  return payload as T;
}
