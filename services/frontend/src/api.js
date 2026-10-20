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
// Rôle lu dans le JWT (payload base64) : 'banker' ou 'client'.
export function getRole() {
  const t = getToken();
  if (!t) return null;
  try { return JSON.parse(atob(t.split(".")[1])).role || "client"; } catch { return null; }
}

async function req(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const t = getToken();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  const res = await fetch(path, { ...opts, headers });
  // Jeton expiré / invalide (JWT 60 min) : on renvoie vers le login.
  // Hors /auth/ pour garder le message "invalid credentials" du formulaire de connexion.
  if (res.status === 401 && t && !path.startsWith("/auth/")) {
    clearToken();
    window.location.href = "/";
    return new Promise(() => {}); // la page se recharge : ne pas afficher d'erreur
  }
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

// ---- Interface banquier (compte de rôle 'banker') ----
export const bankAccounts = () => req("/api/bank/accounts");
export const bankTransactions = (username = "") =>
  req(`/api/bank/transactions${username ? `?username=${encodeURIComponent(username)}` : ""}`);
export const bankCredit = (username, amount, note) =>
  req("/api/bank/credit", { method: "POST", body: JSON.stringify({ username, amount, note }) });
export const bankDebit = (username, amount, note) =>
  req("/api/bank/debit", { method: "POST", body: JSON.stringify({ username, amount, note }) });
// Config du livret d'epargne (taux + intervalle), pilotee par le banquier.
export const bankSavingsConfig = () => req("/api/bank/savings-config");
export const setBankSavingsConfig = (rate, interval) =>
  req("/api/bank/savings-config", { method: "POST", body: JSON.stringify({ rate, interval }) });

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
// Événements serveur live (logs ingérés par le RAG) — pour le panneau de l'assistant.
export async function assistantEvents() {
  try { const r = await fetch("/assistant/events", { cache: "no-store" }); if (!r.ok) return []; const j = await r.json(); return (j.events || "").split("\n").filter(Boolean); }
  catch { return []; }
}

// État + timeline du moteur de remédiation (via proxy nginx /orch).
export async function orchStatus() {
  try {
    const r = await fetch("/orch/status");
    return await r.json();
  } catch { return null; }
}

// Vue du cluster haute dispo (principal/secours + qui sert). Via /api (bascule nginx).
export async function haCluster() {
  try {
    const r = await fetch("/api/ha/cluster", { cache: "no-store" });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

// ---- Jeu : leaderboard, managers banquier (enchères/quiz/intel), suspicion ----
export const leaderboard = () => req("/api/leaderboard");
export const bankAuctions = () => req("/api/bank/auctions");
export const createAuction = (title, item_value, min_bid, perk_kind, perk_value, duration) =>
  req("/api/bank/auctions", { method: "POST", body: JSON.stringify({ title, item_value, min_bid, perk_kind, perk_value, duration }) });
export const closeAuction = (id) => req(`/api/bank/auctions/${id}/close`, { method: "POST" });
export const bankQuizzes = () => req("/api/bank/quizzes");
export const createQuiz = (question, answer, prize) =>
  req("/api/bank/quizzes", { method: "POST", body: JSON.stringify({ question, answer, prize }) });
export const bankIntelOffers = () => req("/api/bank/intel/offers");
export const createIntelOffer = (target, price) =>
  req("/api/bank/intel/offer", { method: "POST", body: JSON.stringify({ target, price }) });
export async function gameSuspicion() {
  try { const r = await fetch("/api/game/suspicion", { cache: "no-store" }); if (!r.ok) return null; return r.json(); }
  catch { return null; }
}

// Première valeur scalaire d'un résultat instantané.
export function scalar(result) {
  if (!result || !result.length) return 0;
  const v = parseFloat(result[0].value?.[1]);
  return Number.isFinite(v) ? v : 0;
}
