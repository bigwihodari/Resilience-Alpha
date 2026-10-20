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
async function jget(path, fallback) {
  try { const r = await fetch(path, { headers: authH(), cache: "no-store" }); if (!r.ok) return fallback; return r.json(); }
  catch { return fallback; }
}
export const getNetworth = () => jget("/api/me/networth", null);
export const getLeaderboard = () => jget("/api/leaderboard", { board: [], target: 1000000, winner: null });
// Livrets
export const getLivrets = () => jget("/api/livrets", { principal: { balance: 0, rate: 0 }, livrets: [], interval: 30 });
export const createLivret = (name) => jpost("/api/livrets", { name }, authH());
export const livretDeposit = (id, amount) => jpost(`/api/livrets/${id}/deposit`, { amount }, authH());
export const livretWithdraw = (id, amount) => jpost(`/api/livrets/${id}/withdraw`, { amount }, authH());
export const livretUpgrade = (id) => jpost(`/api/livrets/${id}/upgrade`, {}, authH());
// Shop
export const getShop = () => jget("/api/shop", { items: [] });
export const shopBuy = (ukey) => jpost("/api/shop/buy", { ukey }, authH());
// Mailbox / enchères / quiz
export async function getMail() { const r = await jget("/api/mail", { mail: [] }); return r.mail || []; }
export const markMailRead = (id) => jpost(`/api/mail/${id}/read`, {}, authH());
export async function getAuctions() { const r = await jget("/api/auctions", { auctions: [] }); return r.auctions || []; }
export const bidAuction = (id, amount) => jpost(`/api/auctions/${id}/bid`, { amount }, authH());
export async function getQuizzes() { const r = await jget("/api/quizzes", { quizzes: [] }); return r.quizzes || []; }
export const answerQuiz = (id, answer) => jpost(`/api/quizzes/${id}/answer`, { answer }, authH());
// Chat
export async function getRooms() { const r = await jget("/api/chat/rooms", { rooms: [] }); return r.rooms || []; }
export const createRoom = (name, members) => jpost("/api/chat/rooms", { name, members }, authH());
export const addRoomMember = (id, member) => jpost(`/api/chat/rooms/${id}/members`, { member }, authH());
export async function getRoomMessages(id, after = 0) { const r = await jget(`/api/chat/rooms/${id}/messages?after=${after}`, { messages: [] }); return r.messages || []; }
export const postRoomMessage = (id, body) => jpost(`/api/chat/rooms/${id}/messages`, { body }, authH());
// Dino
export const dinoClaim = (score, multiplier) => jpost("/api/dino/claim", { score, multiplier }, authH());

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
