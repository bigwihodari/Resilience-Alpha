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

// ---- Prometheus (via proxy nginx /prom) : graphes intégrés au cockpit ----
export async function promInstant(query) {
  try {
    const r = await fetch(`/prom/api/v1/query?query=${encodeURIComponent(query)}`);
    const j = await r.json();
    return j?.data?.result ?? [];
  } catch { return []; }
}
export async function promRange(query, minutes = 15, step = 15) {
  try {
    const end = Math.floor(Date.now() / 1000);
    const start = end - minutes * 60;
    const r = await fetch(
      `/prom/api/v1/query_range?query=${encodeURIComponent(query)}&start=${start}&end=${end}&step=${step}`
    );
    const j = await r.json();
    return j?.data?.result ?? [];
  } catch { return []; }
}
// Assistant RAG (via proxy nginx /assistant).
export async function askAssistant(question) {
  const r = await fetch("/assistant/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// État + timeline du moteur de remédiation (via proxy nginx /orch).
export async function orchStatus() {
  try {
    const r = await fetch("/orch/status");
    return await r.json();
  } catch { return null; }
}

// Première valeur scalaire d'un résultat instantané.
export function scalar(result) {
  if (!result || !result.length) return 0;
  const v = parseFloat(result[0].value?.[1]);
  return Number.isFinite(v) ? v : 0;
}
