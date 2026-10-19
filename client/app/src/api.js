const TOKEN_KEY = "ra_client_token";
const USER_KEY = "ra_client_user";

export function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } }
export function getUser() { try { return localStorage.getItem(USER_KEY); } catch { return null; } }
export function setSession(t, u) { try { localStorage.setItem(TOKEN_KEY, t); localStorage.setItem(USER_KEY, u); } catch { /* */ } }
export function clearSession() { try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch { /* */ } }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function authH() { const t = getToken(); return t ? { Authorization: `Bearer ${t}` } : {}; }

async function jpost(path, body, headers = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || `HTTP ${r.status}`); }
  return r.json();
}

export const login = (username, password) => jpost("/auth/login", { username, password });
export const register = (username, password) => jpost("/auth/register", { username, password });

export async function getAccount() { const r = await fetch("/api/accounts/me", { headers: authH() }); if (!r.ok) throw new Error("compte indisponible"); return r.json(); }
export async function listTx() { const r = await fetch("/api/transactions", { headers: authH() }); if (!r.ok) throw new Error("historique indisponible"); return r.json(); }
export async function searchUsers(q) { const r = await fetch("/api/users?q=" + encodeURIComponent(q), { headers: authH() }); if (!r.ok) return []; return r.json(); }

// Paiement résilient : même clé d'idempotence sur tous les essais -> si le serveur
// bascule (principal KO), le ré-essai aboutit sans double débit (exactly-once).
export async function pay(recipient, amount, onRetry) {
  const key = (self.crypto && self.crypto.randomUUID) ? self.crypto.randomUUID() : String(Date.now()) + Math.random();
  let lastErr;
  for (let i = 0; i < 5; i++) {
    let r;
    try {
      r = await fetch("/api/transactions", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authH() },
        body: JSON.stringify({ recipient, amount, idempotency_key: key }),
      });
    } catch (e) {
      lastErr = e; if (onRetry) onRetry(i + 1); await sleep(1000); continue; // serveur injoignable -> ré-essai
    }
    if (r.ok) return r.json();
    if ([502, 503, 504].includes(r.status)) { lastErr = new Error("serveur indisponible"); if (onRetry) onRetry(i + 1); await sleep(1000); continue; }
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(e.detail || `HTTP ${r.status}`); // erreur métier (fonds, etc.) -> pas de ré-essai
  }
  throw lastErr || new Error("échec du paiement");
}
