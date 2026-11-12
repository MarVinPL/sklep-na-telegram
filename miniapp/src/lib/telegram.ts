export function getTelegramInitData(): string {
  return window.Telegram?.WebApp.initData ?? "";
}

export function isTelegramContextAvailable(): boolean {
  return getTelegramInitData().length > 0;
}
