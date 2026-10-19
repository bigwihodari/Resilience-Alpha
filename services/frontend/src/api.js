const TOKEN_KEY = "ra_token";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t) {
  try { localStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ }
}
export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

async function req(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const t = getToken();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    const e = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(e.detail || `HTTP ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

export const login = (username, password) =>
  req("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
export const getAccount = () => req("/api/accounts/me");
export const createTx = (amount, recipient) =>
  req("/api/transactions", { method: "POST", body: JSON.stringify({ amount, recipient }) });
export const listTx = () => req("/api/transactions");
