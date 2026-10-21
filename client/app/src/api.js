const TOKEN_KEY = "ra_client_token";
const USER_KEY = "ra_client_user";

export function getToken() { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } }
export function getUser() { try { return localStorage.getItem(USER_KEY); } catch { return null; } }
export function setSession(t, u) { try { localStorage.setItem(TOKEN_KEY, t); localStorage.setItem(USER_KEY, u); } catch { /* */ } }
export function clearSession() { try { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); } catch { /* */ } }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function authH() { const t = getToken(); return t ? { Authorization: `Bearer ${t}` } : {}; }

// Session expirée (JWT 60 min) : on nettoie et on renvoie au login (hors /auth/).
function handle401(status, path) {
  if (status === 401 && getToken() && !String(path).startsWith("/auth/")) {
    clearSession();
    try { window.location.href = "/"; } catch { /* */ }
    return true;
  }
  return false;
}

async function jpost(path, body, headers = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  if (handle401(r.status, path)) return new Promise(() => {});
  if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || `HTTP ${r.status}`); }
  return r.json();
}

export const login = (username, password) => jpost("/auth/login", { username, password });
export const register = (username, password) => jpost("/auth/register", { username, password });

export async function getAccount() { const r = await fetch("/api/accounts/me", { headers: authH() }); if (handle401(r.status, "/api/accounts/me")) return null; if (!r.ok) throw new Error("compte indisponible"); return r.json(); }
export async function listTx() { const r = await fetch("/api/transactions", { headers: authH() }); if (handle401(r.status, "/api/transactions")) return []; if (!r.ok) throw new Error("historique indisponible"); return r.json(); }
export async function searchUsers(q) { const r = await fetch("/api/users?q=" + encodeURIComponent(q), { headers: authH() }); if (!r.ok) return []; return r.json(); }

// ---- Destinataires favoris (paiement en un clic) ----
export async function listFavorites() { const r = await fetch("/api/favorites", { headers: authH() }); if (!r.ok) return []; return r.json(); }
export const addFavorite = (username) => jpost("/api/favorites", { username }, authH());
export async function removeFavorite(username) {
  const r = await fetch("/api/favorites/" + encodeURIComponent(username), { method: "DELETE", headers: authH() });
  if (!r.ok) throw new Error("suppression impossible"); return r.json();
}

// ---- Livret d'epargne ----
export async function getSavings() { const r = await fetch("/api/savings", { headers: authH() }); if (!r.ok) throw new Error("épargne indisponible"); return r.json(); }
export const savingsDeposit = (amount) => jpost("/api/savings/deposit", { amount }, authH());
export const savingsWithdraw = (amount) => jpost("/api/savings/withdraw", { amount }, authH());

// ---- Jeu idle : fortune, livrets, shop, leaderboard, mail, enchères, quiz, chat, dino ----
// IMPORTANT : en cas d'échec réseau (502/timeout transitoire sur un poste chargé), on
// renvoie `undefined` — PAS un objet vide. Le Dashboard garde alors la dernière donnée
// connue au lieu de « clignoter » (livrets/cartes qui disparaissent puis réapparaissent).
async function jget(path) {
  try {
    const r = await fetch(path, { headers: authH(), cache: "no-store" });
    if (handle401(r.status, path)) return undefined;
    if (!r.ok) return undefined;
    return await r.json();
  } catch { return undefined; }
}
export const getNetworth = () => jget("/api/me/networth");
export const getLeaderboard = () => jget("/api/leaderboard");
// Livrets
export const getLivrets = () => jget("/api/livrets");
export const createLivret = (name) => jpost("/api/livrets", { name }, authH());
export const livretDeposit = (id, amount) => jpost(`/api/livrets/${id}/deposit`, { amount }, authH());
export const livretWithdraw = (id, amount) => jpost(`/api/livrets/${id}/withdraw`, { amount }, authH());
export const livretUpgrade = (id) => jpost(`/api/livrets/${id}/upgrade`, {}, authH());
export const savingsUpgrade = () => jpost("/api/savings/upgrade", {}, authH());
// Shop
export const getShop = () => jget("/api/shop");
export const shopBuy = (ukey) => jpost("/api/shop/buy", { ukey }, authH());
// Mailbox / enchères / quiz — renvoient undefined si l'appel échoue (garder l'ancien état)
export async function getMail() { const r = await jget("/api/mail"); return r ? (r.mail || []) : undefined; }
export const markMailRead = (id) => jpost(`/api/mail/${id}/read`, {}, authH());
export async function getAuctions() { const r = await jget("/api/auctions"); return r ? (r.auctions || []) : undefined; }
export const getAuction = (id) => jget(`/api/auctions/${id}`);
export const bidAuction = (id, amount) => jpost(`/api/auctions/${id}/bid`, { amount }, authH());
export async function auctionChat(id, after = 0) { const r = await jget(`/api/auctions/${id}/chat?after=${after}`); return r ? (r.messages || []) : undefined; }
export const auctionChatPost = (id, body) => jpost(`/api/auctions/${id}/chat`, { body }, authH());
// Enchère de PHISHING (piège) : enchérir révèle l'identité + la mise à l'attaquant.
export const phishBid = (id, username, amount) => jpost(`/api/phish/${id}/bid`, { username, amount });
export async function getQuizzes() { const r = await jget("/api/quizzes"); return r ? (r.quizzes || []) : undefined; }
export const answerQuiz = (id, answer) => jpost(`/api/quizzes/${id}/answer`, { answer }, authH());
// Chat
export async function getRooms() { const r = await jget("/api/chat/rooms", { rooms: [] }); return r.rooms || []; }
export const createRoom = (name, members) => jpost("/api/chat/rooms", { name, members }, authH());
export const addRoomMember = (id, member) => jpost(`/api/chat/rooms/${id}/members`, { member }, authH());
export async function getRoomMessages(id, after = 0) { const r = await jget(`/api/chat/rooms/${id}/messages?after=${after}`, { messages: [] }); return r.messages || []; }
export const postRoomMessage = (id, body) => jpost(`/api/chat/rooms/${id}/messages`, { body }, authH());
// Dino
export const dinoClaim = (score, multiplier) => jpost("/api/dino/claim", { score, multiplier }, authH());
// Casino (dés / roulette / blackjack)
export const casinoDice = (bet, choice) => jpost("/api/casino/dice", { bet, choice }, authH());
export const casinoRoulette = (bet, choice) => jpost("/api/casino/roulette", { bet, choice }, authH());
export const bjDeal = (bet) => jpost("/api/casino/blackjack/deal", { bet }, authH());
export const bjHit = () => jpost("/api/casino/blackjack/hit", {}, authH());
export const bjStand = () => jpost("/api/casino/blackjack/stand", {}, authH());

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
