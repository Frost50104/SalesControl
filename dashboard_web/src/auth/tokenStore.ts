const TOKEN_KEY = 'adminToken';
const BASE_URL_KEY = 'apiBaseUrl';

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function getBaseUrl(): string | null {
  return sessionStorage.getItem(BASE_URL_KEY);
}

export function setBaseUrl(url: string): void {
  sessionStorage.setItem(BASE_URL_KEY, url);
}

export function clearAuth(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(BASE_URL_KEY);
}
