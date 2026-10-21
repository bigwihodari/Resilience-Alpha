import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getUser, clearSession,
  getNetworth, getLeaderboard,
  getLivrets, createLivret, livretDeposit, livretWithdraw, livretUpgrade, savingsUpgrade,
  savingsDeposit, savingsWithdraw,
  getShop, shopBuy,
  getMail, markMailRead, getAuctions, getAuction, bidAuction, auctionChat, auctionChatPost, phishBid, getQuizzes, answerQuiz,
  listTx, searchUsers, pay, listFavorites, addFavorite, removeFavorite,
} from "../api.js";
import ChatWidget from "../widgets/ChatWidget.jsx";
import DinoWidget from "../widgets/DinoWidget.jsx";
import Casino from "./Casino.jsx";

const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} €`;

export default function Dashboard() {
  const me = getUser();
  const nav = useNavigate();
  const [tab, setTab] = useState("livrets");
  const [nw, setNw] = useState(null);
  const [lb, setLb] = useState({ board: [], target: 1000000, winner: null });
  const [liv, setLiv] = useState({ principal: { balance: 0, rate: 0 }, livrets: [], interval: 30 });
  const [shop, setShop] = useState({ items: [] });
  const [mail, setMail] = useState([]);
  const [mailModal, setMailModal] = useState(null);
  const [aucId, setAucId] = useState(null);       // enchère ouverte (page dédiée)
  const [auc, setAuc] = useState(null);
  const [aucChat, setAucChat] = useState([]);
  const aucChatLast = useRef(0);
  const [phishMail, setPhishMail] = useState(null);  // mail de phishing ouvert
  const [phishResult, setPhishResult] = useState(null);
  const [auctions, setAuctions] = useState([]);
  const [quizzes, setQuizzes] = useState([]);
  const [nowTick, setNowTick] = useState(Date.now());
  const auctionsAt = useRef(Date.now());
  const refreshTimer = useRef(null);
  // paiement
  const [txs, setTxs] = useState([]);
  const [favs, setFavs] = useState([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [recipient, setRecipient] = useState("");
  const [payAmount, setPayAmount] = useState("20");
  const [toast, setToast] = useState(null);
  const flash = (text, type = "ok") => { setToast({ text, type }); setTimeout(() => setToast(null), 3500); };

  async function refresh() {
    const [n, l, lv, sh, mb, au, qz, tx, fv] = await Promise.all([
      getNetworth(), getLeaderboard(), getLivrets(), getShop(), getMail(), getAuctions(), getQuizzes(),
      listTx().catch(() => undefined), listFavorites().catch(() => undefined),
    ]);
    // Chaque setState n'écrase l'état QUE si l'appel a réussi (valeur définie).
    // Un échec transitoire (502) laisse la dernière donnée affichée -> pas de clignotement.
    if (n) setNw(n);
    if (l) setLb(l);
    if (lv) setLiv(lv);
    if (sh) setShop(sh);
    if (mb) setMail(mb);
    if (au) { setAuctions(au); auctionsAt.current = Date.now(); }
    if (qz) setQuizzes(qz);
    if (tx) setTxs(tx);
    if (fv) setFavs(fv);
  }

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, 5000);
    const tick = setInterval(() => setNowTick(Date.now()), 1000);
    let ws, stopped = false, retry, ping;
    const connect = () => {
      try {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws`);
        ws.onopen = () => { clearInterval(ping); ping = setInterval(() => { try { ws.send("ping"); } catch { /* */ } }, 25000); };
        ws.onmessage = (e) => {
          try {
            const d = JSON.parse(e.data);
            // Notifications live : enchère/quiz qui arrivent en direct.
            if (d.type === "auction" && d.op === "open") flash("🔔 Nouvelle enchère dans le Marché !");
            if (d.type === "quiz" && d.op === "open") flash("🧠 Nouveau quiz — réponds vite !");
            if (d.type === "quiz" && d.op === "win" && d.winner && d.winner !== me) flash(`🧠 Quiz remporté par ${d.winner}`, "err");
            if (["tx", "win", "mail", "auction", "quiz"].includes(d.type)) refreshSoon(600);
          } catch { /* */ }
        };
        ws.onclose = () => { clearInterval(ping); if (!stopped) retry = setTimeout(connect, 2000); };
        ws.onerror = () => { try { ws.close(); } catch { /* */ } };
      } catch { retry = setTimeout(connect, 2000); }
    };
    connect();
    return () => { stopped = true; clearInterval(poll); clearInterval(tick); clearInterval(retry); clearInterval(ping); clearTimeout(refreshTimer.current); try { ws && ws.close(); } catch { /* */ } };
  }, []);

  // Rafraîchissement DÉBOUNCÉ : les clics rapides (spam d'upgrade) et les events WS
  // ne déclenchent qu'UN seul refresh groupé -> fini le flood de requêtes et les 502.
  function refreshSoon(delay = 350) {
    clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(() => { refresh(); }, delay);
  }
  // `apply` (optionnel) met à jour l'état localement depuis la réponse pour un retour
  // instantané pendant le spam, sans attendre le refresh groupé.
  async function act(fn, ok, apply) {
    try {
      const r = await fn();
      if (apply) apply(r);
      if (ok) flash(typeof ok === "function" ? ok(r) : ok);
      refreshSoon();
    } catch (e) { flash(e.message, "err"); }
  }
  // Maj optimiste du solde courant (fortune corrigée au prochain refresh groupé).
  const patchCourant = (bal) => { if (bal != null) setNw((p) => (p ? { ...p, courant: bal } : p)); };

  // ---- Enchère ouverte (page dédiée via le mail) : poll de l'enchère + du chat ----
  function openAuction(id) { if (!id) return; setMailModal(null); setPhishMail(null); setAuc(null); setAucChat([]); aucChatLast.current = 0; setAucId(id); }
  function openPhish(mail) { setMailModal(null); setPhishResult(null); setPhishMail(mail); }
  useEffect(() => {
    if (!aucId) return;
    let stop = false;
    const tick = async () => {
      try { const a = await getAuction(aucId); if (!stop && a) setAuc(a); } catch { /* */ }
      try { const c = await auctionChat(aucId, aucChatLast.current); if (!stop && c && c.length) { aucChatLast.current = c[c.length - 1].id; setAucChat((p) => [...p, ...c]); } } catch { /* */ }
    };
    tick();
    const iv = setInterval(tick, 1500);
    return () => { stop = true; clearInterval(iv); };
  }, [aucId]);
  async function sendAucChat() {
    const el = document.getElementById("auc-chat-input"); const t = (el && el.value || "").trim();
    if (!t || !aucId) return; el.value = "";
    try { await auctionChatPost(aucId, t); const c = await auctionChat(aucId, aucChatLast.current); if (c && c.length) { aucChatLast.current = c[c.length - 1].id; setAucChat((p) => [...p, ...c]); } } catch { /* */ }
  }
  async function doPhishBid() {
    const el = document.getElementById("phish-amt"); const a = Math.max(1, parseFloat(el && el.value) || 0);
    try { const r = await phishBid(phishMail.ref_id, me, a); setPhishResult(r && (r.message || "Mise enregistrée.")); await refresh(); }
    catch (e) { setPhishResult(e.message); }
  }
  // Montant saisi pour un livret (champ `amt-<clé>`), au clic. Défaut 100, min 1.
  const amtOf = (k) => { const el = document.getElementById("amt-" + k); return Math.max(1, Math.floor(parseFloat(el && el.value) || 100)); };
  const applyPrincipalBoost = (r) => { setLiv((p) => ({ ...p, principal: { ...p.principal, level: r.level, rate: r.rate, upgrade_cost: r.next_cost } })); patchCourant(r.balance); };
  const applyLivretBoost = (r) => { setLiv((p) => ({ ...p, livrets: p.livrets.map((x) => (x.id === r.id ? { ...x, level: r.level, rate: r.rate, upgrade_cost: r.next_cost } : x)) })); patchCourant(r.balance); };
  const applyShopBuy = (r) => { setShop((p) => ({ ...p, items: p.items.map((x) => (x.ukey === r.ukey ? { ...x, level: r.level, next_cost: r.next_cost } : x)) })); patchCourant(r.balance); };

  async function doSearch(v) { setQ(v); if (v.trim().length < 1) { setResults([]); return; } setResults(await searchUsers(v.trim())); }
  function choose(u) { setRecipient(u); setQ(u); setResults([]); }
  async function doPay() {
    if (!recipient) { flash("Choisis un destinataire.", "err"); return; }
    try {
      const r = await pay(recipient, parseFloat(payAmount), () => flash("Reprise (bascule serveur)…", "err"));
      flash(`Paiement à ${recipient} ${r.resumed ? "(repris)" : ""} — solde ${euro(r.new_balance)}`);
      setRecipient(""); setQ(""); setResults([]); await refresh();
    } catch (e) { flash(e.message, "err"); }
  }
  async function openMailItem(m) {
    setMailModal(m);
    if (!m.read) { try { await markMailRead(m.id); await refresh(); } catch { /* */ } }
  }
  // secondes restantes d'une enchère (timer local lissé entre deux refresh)
  const secLeft = (a) => a.seconds_left == null ? null : Math.max(0, Math.round(a.seconds_left - (nowTick - auctionsAt.current) / 1000));
  const perkColor = (k) => k === "upgrade" ? "bg-fuchsia-100 text-fuchsia-700" : k === "pct" ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700";

  const progress = nw ? Math.min(100, (nw.networth / nw.target) * 100) : 0;
  const myRank = lb.board.findIndex((b) => b.name === me) + 1;
  const unread = mail.filter((m) => !m.read).length;
  const isFav = recipient && favs.some((f) => f.username === recipient);

  const TabBtn = ({ id, label, badge }) => (
    <button onClick={() => setTab(id)} role="tab" aria-selected={tab === id}
      className={`px-4 py-2 rounded-xl text-sm font-bold whitespace-nowrap transition focus-visible:outline-none ${tab === id ? "bg-accent text-white shadow-md scale-[1.03]" : "bg-white text-ink/70 hover:bg-lavsoft hover:text-ink"}`}>
      {label}{badge ? <span className="ml-1.5 bg-red-500 text-white text-[10px] px-1.5 py-0.5 rounded-full">{badge}</span> : null}
    </button>
  );

  return (
    <div className="max-w-5xl mx-auto p-4 pb-28">
      {/* En-tête */}
      <div className="flex items-center gap-3 mb-3">
        <div>
          <div className="text-[11px] tracking-widest text-accent font-bold">RESILIENCE-ALPHA · JOUEUR</div>
          <div className="text-lg font-extrabold text-ink">{me}</div>
        </div>
        <button className="ml-auto text-sm bg-white px-3 py-1.5 rounded-lg shadow hover:bg-lavsoft" onClick={() => { clearSession(); nav("/"); }}>Déconnexion</button>
      </div>

      {/* Fortune */}
      <div className="bg-gradient-to-br from-ink via-accent to-[#6C5CE7] text-white rounded-3xl p-6 shadow-xl mb-4">
        <div className="flex items-end justify-between flex-wrap gap-2">
          <div>
            <div className="text-sm opacity-80">Fortune totale</div>
            <div className="text-5xl font-black mt-1 tabular-nums">{nw ? euro(nw.networth) : "…"}</div>
            <div className="text-xs opacity-75 mt-1">Courant {euro(nw?.courant)} · Livret princ. {euro(nw?.savings)} · Livrets {euro(nw?.livrets_total)}</div>
          </div>
          <div className="text-right">
            <div className="text-sm opacity-80">Objectif</div>
            <div className="text-2xl font-extrabold">{euro(lb.target)}</div>
            {myRank > 0 && <div className="text-xs opacity-75 mt-1">Rang #{myRank} / {lb.board.length}</div>}
          </div>
        </div>
        <div className="mt-4 h-3 bg-white/20 rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-green-300 to-green-500 transition-all duration-700" style={{ width: `${progress}%` }} />
        </div>
        <div className="text-xs opacity-80 mt-1">{progress.toFixed(2)} % vers le milliard</div>
      </div>

      {lb.winner && <div className="bg-amber-400 text-ink rounded-2xl p-4 mb-4 text-center font-extrabold shadow-lg animate-pulse">🏆 VICTOIRE — {lb.winner.name} ({lb.winner.camp}) a atteint le milliard !</div>}

      {/* Menu (onglets) — collant en haut au défilement */}
      <div role="tablist" aria-label="Navigation" className="sticky top-0 z-30 flex gap-2 overflow-x-auto py-2 mb-4 -mx-4 px-4 bg-[#E4E6F3]/85 backdrop-blur">
        <TabBtn id="livrets" label="💰 Livrets & Shop" />
        <TabBtn id="marche" label="📬 Marché" badge={unread || null} />
        <TabBtn id="payer" label="💸 Payer" />
        <TabBtn id="casino" label="🎰 Casino" />
        <TabBtn id="classement" label="🏁 Classement" />
      </div>

      {toast && <div className={`fixed bottom-24 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl shadow-lg text-sm font-semibold ${toast.type === "ok" ? "bg-green-600 text-white" : "bg-red-600 text-white"}`}>{toast.text}</div>}

      {/* Modal e-mail : lecture + boutons d'action (enchère / quiz) */}
      {mailModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setMailModal(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-2">
              {/* Le phishing s'affiche comme une invitation d'enchère : à toi de le repérer. */}
              <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${(mailModal.kind === "auction" || mailModal.kind === "phishing") ? "bg-green-100 text-green-700" : mailModal.kind === "quiz" ? "bg-amber-100 text-amber-700" : mailModal.kind === "prize" ? "bg-fuchsia-100 text-fuchsia-700" : "bg-lavsoft text-accent"}`}>{(mailModal.kind === "auction" || mailModal.kind === "phishing") ? "enchère" : mailModal.kind}</span>
              <h3 className="font-extrabold text-ink flex-1 leading-tight">{mailModal.subject}</h3>
              <button onClick={() => setMailModal(null)} className="text-ink/40 hover:text-ink text-2xl leading-none">×</button>
            </div>
            {mailModal.html
              ? <div className="mt-3 border border-lavsoft rounded-lg overflow-hidden" dangerouslySetInnerHTML={{ __html: mailModal.html }} />
              : <p className="text-sm text-ink/80 mt-3 whitespace-pre-wrap">{mailModal.body}</p>}
            <div className="flex flex-wrap gap-2 mt-4">
              {mailModal.kind === "auction" && <button onClick={() => openAuction(mailModal.ref_id)} className="bg-accent text-white font-semibold px-4 py-2 rounded-lg hover:bg-ink text-sm">🔨 Accéder à l'enchère</button>}
              {mailModal.kind === "phishing" && <button onClick={() => openPhish(mailModal)} className="bg-accent text-white font-semibold px-4 py-2 rounded-lg hover:bg-ink text-sm">🔨 Accéder à l'enchère</button>}
              {mailModal.kind === "quiz" && <button onClick={() => { setTab("marche"); setMailModal(null); }} className="bg-amber-500 text-white font-semibold px-4 py-2 rounded-lg hover:bg-amber-600 text-sm">🧠 Répondre au quiz</button>}
              <button onClick={() => setMailModal(null)} className="bg-lavsoft text-accent font-semibold px-4 py-2 rounded-lg hover:bg-lav/40 text-sm">Fermer</button>
            </div>
          </div>
        </div>
      )}

      {/* Page ENCHÈRE (dédiée) : démarre à 2 participants, chat en direct */}
      {aucId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setAucId(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-5 max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            {!auc ? <div className="text-ink/50 text-sm py-6 text-center">Chargement de l'enchère…</div> : auc.status !== "open" ? (
              <div className="text-center py-6">
                <div className="text-xl font-black text-ink">{auc.title}</div>
                <div className="mt-2 text-sm text-ink/60">Enchère terminée{auc.winner ? ` — remportée par ${auc.winner}` : ""}.</div>
                <button onClick={() => setAucId(null)} className="mt-4 bg-lavsoft text-accent font-semibold px-4 py-2 rounded-lg">Fermer</button>
              </div>
            ) : (
              <>
                <div className="flex items-start gap-2">
                  <div className="flex-1">
                    <div className="font-extrabold text-ink text-lg">{auc.title}</div>
                    <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${perkColor(auc.perk_kind)}`}>🎁 {auc.perk_label}</span>
                  </div>
                  <button onClick={() => setAucId(null)} className="text-ink/40 hover:text-ink text-2xl leading-none">×</button>
                </div>
                <div className="mt-2 text-sm text-ink/70">
                  Mise min {euro(auc.min_bid)} · {auc.participants} participant(s)
                  {auc.highest_bid != null && <> · meilleure mise <b className="text-ink">{euro(auc.highest_bid)}</b></>}
                </div>
                {!auc.started
                  ? <div className="mt-2 text-sm font-semibold text-amber-700 bg-amber-50 rounded-lg px-3 py-2">⏳ En attente d'un 2e participant — enchéris pour lancer la compétition !</div>
                  : <div className="mt-2 text-sm font-mono font-bold text-accent">⏳ {auc.seconds_left}s restantes</div>}
                <div className="flex gap-2 mt-3 items-center">
                  <input id="auc-bid" type="number" defaultValue={Math.max(auc.min_bid || 50, Math.round(Math.max(auc.min_bid || 0, auc.highest_bid || 0) + 10))} className="w-28 border border-lav rounded-lg px-2 py-1.5 text-sm" />
                  <button onClick={() => act(() => bidAuction(auc.id, parseFloat(document.getElementById("auc-bid").value)), (r) => r.started ? "Enchère placée" : "Mise placée — en attente d'un 2e participant")} className="bg-accent text-white font-semibold px-4 py-2 rounded-lg hover:bg-ink text-sm">Enchérir</button>
                </div>
                <div className="mt-4">
                  <div className="font-bold text-ink text-sm mb-1">💬 Chat de l'enchère</div>
                  <div className="bg-lavsoft/50 rounded-lg p-2 h-40 overflow-auto text-sm space-y-1">
                    {aucChat.length === 0 && <div className="text-ink/40 text-xs">Aucun message — lance la discussion.</div>}
                    {aucChat.map((m) => <div key={m.id} className="break-words"><b className={m.author === me ? "text-accent" : "text-ink"}>{m.author}</b> <span className="text-ink/70">{m.body}</span></div>)}
                  </div>
                  <div className="flex gap-2 mt-2">
                    <input id="auc-chat-input" onKeyDown={(e) => e.key === "Enter" && sendAucChat()} placeholder="Message…" className="flex-1 border border-lav rounded-lg px-2 py-1.5 text-sm" />
                    <button onClick={sendAucChat} className="bg-ink text-white font-semibold px-3 rounded-lg text-sm">➤</button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Page PHISHING (piège) : mise en scène HTML + enchérir révèle identité/mise à l'attaquant */}
      {phishMail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setPhishMail(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-5 max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-2">
              <h3 className="font-extrabold text-ink flex-1 leading-tight">{phishMail.subject}</h3>
              <button onClick={() => setPhishMail(null)} className="text-ink/40 hover:text-ink text-2xl leading-none">×</button>
            </div>
            {phishMail.html
              ? <div className="mt-3 border border-lavsoft rounded-lg overflow-hidden" dangerouslySetInnerHTML={{ __html: phishMail.html }} />
              : <p className="text-sm text-ink/80 mt-3 whitespace-pre-wrap">{phishMail.body}</p>}
            {phishResult
              ? <div className="mt-4 text-sm font-semibold text-red-700 bg-red-50 rounded-lg px-3 py-2">{phishResult}</div>
              : (
                <div className="flex gap-2 mt-4 items-center">
                  <input id="phish-amt" type="number" defaultValue={100} className="w-28 border border-lav rounded-lg px-2 py-1.5 text-sm" placeholder="ta mise €" />
                  <button onClick={doPhishBid} className="bg-accent text-white font-semibold px-4 py-2 rounded-lg hover:bg-ink text-sm">🔨 Enchérir</button>
                </div>
              )}
            <button onClick={() => setPhishMail(null)} className="mt-3 block text-xs text-ink/50">Fermer</button>
          </div>
        </div>
      )}

      {/* LIVRETS & SHOP */}
      {tab === "livrets" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="space-y-3">
            <div className="bg-white rounded-2xl shadow p-4">
              <div className="flex items-center justify-between">
                <div className="font-bold text-ink">Livret principal <span className="text-xs text-ink/40">niv {liv.principal.level || 0}</span></div>
                {liv.principal.balance >= (liv.livret_max || 150000)
                  ? <div className="text-xs font-bold text-red-600 animate-pulse">PLEIN — retire pour relancer</div>
                  : <div className="text-xs text-green-600 font-semibold">+{((liv.principal.rate || 0) * 100).toFixed(2)} % / {liv.interval}s</div>}
              </div>
              <div className="text-3xl font-extrabold text-green-700 mt-1">{euro(liv.principal.balance)} <span className="text-sm font-semibold text-ink/40">/ {euro(liv.livret_max || 150000)}</span></div>
              <div className="flex flex-wrap items-center gap-2 mt-2">
                <input id="amt-principal" type="number" min="1" defaultValue="100" className="w-24 border border-lav rounded-lg px-2 py-1.5 text-sm" title="Montant à déposer / retirer" />
                <button onClick={() => { const a = amtOf("principal"); act(() => savingsDeposit(a), `Dépôt de ${euro(a)}`); }} className="text-xs bg-green-600 text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-green-700">Déposer</button>
                <button onClick={() => { const a = amtOf("principal"); act(() => savingsWithdraw(a), `Retrait de ${euro(a)}`); }} className="text-xs bg-ink text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-accent">Retirer</button>
                <button onClick={() => act(() => savingsUpgrade(), (r) => `Taux boosté à +${(r.rate * 100).toFixed(2)} %`, applyPrincipalBoost)} className="text-xs bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">⬆ Booster ({euro(liv.principal.upgrade_cost || 0)})</button>
              </div>
            </div>
            {liv.livrets.map((lv) => (
              <div key={lv.id} className="bg-white rounded-2xl shadow p-4">
                <div className="flex items-center justify-between">
                  <div className="font-bold text-ink">{lv.name} <span className="text-xs text-ink/40">niv {lv.level}</span></div>
                  {lv.balance >= (liv.livret_max || 150000)
                    ? <div className="text-xs font-bold text-red-600 animate-pulse">PLEIN — retire pour relancer</div>
                    : <div className="text-xs text-green-600 font-semibold">+{(lv.rate * 100).toFixed(2)} % / {liv.interval}s</div>}
                </div>
                <div className="text-2xl font-extrabold text-green-700 mt-1">{euro(lv.balance)} <span className="text-sm font-semibold text-ink/40">/ {euro(liv.livret_max || 150000)}</span></div>
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  <input id={`amt-${lv.id}`} type="number" min="1" defaultValue="100" className="w-24 border border-lav rounded-lg px-2 py-1.5 text-sm" title="Montant à déposer / retirer" />
                  <button onClick={() => { const a = amtOf(lv.id); act(() => livretDeposit(lv.id, a), `Dépôt de ${euro(a)}`); }} className="text-xs bg-green-600 text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-green-700">Déposer</button>
                  <button onClick={() => { const a = amtOf(lv.id); act(() => livretWithdraw(lv.id, a), `Retrait de ${euro(a)}`); }} className="text-xs bg-ink text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-accent">Retirer</button>
                  <button onClick={() => act(() => livretUpgrade(lv.id), (r) => `Taux boosté à +${(r.rate * 100).toFixed(2)} %`, applyLivretBoost)} className="text-xs bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">⬆ Booster ({euro(lv.upgrade_cost)})</button>
                </div>
              </div>
            ))}
            <button onClick={() => act(() => createLivret(), "Nouveau livret ouvert")} className="w-full bg-white border-2 border-dashed border-lav text-accent font-semibold py-2.5 rounded-2xl hover:bg-lavsoft">+ Ouvrir un livret</button>
          </div>
          <div className="space-y-4">
            <div className="bg-white rounded-2xl shadow p-4 h-fit">
              <div className="flex items-center gap-2 mb-3">
                <div className="font-bold text-ink">🛒 Boutique</div>
                {shop.discount > 0 && <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-fuchsia-100 text-fuchsia-700">Remise VIP −{shop.discount}%</span>}
              </div>
              <div className="space-y-2">
                {shop.items.map((it) => (
                  <div key={it.ukey} className="flex items-center gap-3 border-b border-lavsoft pb-2">
                    <div className="flex-1"><div className="font-semibold text-sm text-ink">{it.label} <span className="text-xs text-ink/40">niv {it.level}</span></div><div className="text-xs text-ink/50">{it.desc}</div></div>
                    <button onClick={() => act(() => shopBuy(it.ukey), (r) => `${it.label} niv ${r.level}`, applyShopBuy)} className="text-xs bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink whitespace-nowrap">{euro(it.next_cost)}</button>
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-gradient-to-br from-fuchsia-50 to-lavsoft rounded-2xl shadow p-4 h-fit border border-fuchsia-100">
              <div className="font-bold text-ink mb-1">✨ Upgrades spéciales</div>
              <div className="text-xs text-ink/50 mb-3">Impossibles à acheter — se gagnent uniquement aux enchères.</div>
              <div className="space-y-2">
                {(shop.specials || []).map((sp) => (
                  <div key={sp.ukey} className="flex items-center gap-3">
                    <span className="text-xl">{sp.icon}</span>
                    <div className="flex-1">
                      <div className="font-semibold text-sm text-ink">{sp.label} {sp.level > 0 ? <span className="text-xs text-fuchsia-600 font-bold">niv {sp.level}</span> : <span className="text-xs text-ink/30">non débloquée</span>}</div>
                      <div className="text-xs text-ink/50">{sp.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MARCHE */}
      {tab === "marche" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="space-y-3">
            <div className="font-bold text-accent text-sm uppercase tracking-wide">Enchères</div>
            <div className="bg-white/70 border border-dashed border-lav rounded-2xl p-4 text-sm text-ink/60">
              📩 Les enchères arrivent par <b>invitation dans ta boîte mail</b> → ouvre le mail et clique
              « Accéder à l'enchère ». Une enchère <b>démarre dès qu'il y a 2 participants</b>, avec un chat en direct.
              <span className="text-ink/40"> (Attention au phishing : certaines invitations sont des pièges.)</span>
            </div>
            <div className="font-bold text-accent text-sm uppercase tracking-wide mt-4">Quiz automatiques</div>
            {quizzes.filter((q) => q.status === "open").length === 0 && <div className="text-sm text-ink/50">Aucun quiz en cours — un nouveau arrive bientôt…</div>}
            {quizzes.filter((q) => q.status === "open").map((q) => {
              const sl = secLeft(q);
              return (
                <div key={q.id} className="bg-white rounded-2xl shadow p-4">
                  <div className="flex items-start gap-2">
                    <span className="font-semibold text-ink flex-1">{q.question}</span>
                    {sl != null && <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded-full shrink-0 ${sl <= 10 ? "bg-red-100 text-red-700 animate-pulse" : "bg-lavsoft text-accent"}`}>⏳ {sl}s</span>}
                  </div>
                  <div className="text-xs text-green-600 font-semibold mt-1">🧠 Lot : {euro(q.prize)} — 1re bonne réponse</div>
                  <div className="flex gap-2 mt-2 items-center">
                    <input id={`q-${q.id}`} className="flex-1 border border-lav rounded-lg px-2 py-1.5 text-sm" placeholder="Ta réponse…" onKeyDown={(e) => { if (e.key === "Enter") act(() => answerQuiz(q.id, e.target.value), (r) => r.correct ? `Gagné ! +${euro(r.prize)}` : "Mauvaise réponse"); }} />
                    <button onClick={() => act(() => answerQuiz(q.id, document.getElementById(`q-${q.id}`).value), (r) => r.correct ? `Gagné ! +${euro(r.prize)}` : "Mauvaise réponse")} className="text-sm bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">Répondre</button>
                  </div>
                </div>
              );
            })}
          </div>
          <div>
            <div className="font-bold text-accent text-sm uppercase tracking-wide mb-2">Boîte mail</div>
            <div className="bg-white rounded-2xl shadow divide-y divide-lavsoft max-h-[32rem] overflow-auto">
              {mail.length === 0 && <div className="p-4 text-sm text-ink/50">Aucun message.</div>}
              {mail.map((m) => (
                <button key={m.id} onClick={() => openMailItem(m)} className={`w-full text-left p-3 hover:bg-lavsoft/60 transition ${m.read ? "" : "bg-lavsoft/40"}`}>
                  <div className="flex items-center gap-2">
                    {!m.read && <span className="w-2 h-2 rounded-full bg-accent shrink-0"></span>}
                    <span className="font-semibold text-sm text-ink truncate">{m.subject}</span>
                    <span className="ml-auto text-[10px] text-ink/40 shrink-0">{m.kind}</span>
                    <span className="text-ink/30 shrink-0">›</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* PAYER */}
      {tab === "payer" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="bg-white rounded-2xl shadow p-5">
            <h2 className="font-bold text-lg text-ink mb-1">Payer un ami</h2>
            <div className="text-sm text-ink/60 mb-3">Solde courant : <b>{euro(nw?.courant)}</b></div>
            {favs.length > 0 && (
              <>
                <label className="block text-sm font-semibold mb-1">Favoris</label>
                <div className="flex flex-wrap gap-2 mb-3">
                  {favs.map((f) => (
                    <span key={f.username} className={`inline-flex items-center gap-1 text-sm px-3 py-1 rounded-full ${recipient === f.username ? "bg-accent text-white" : "bg-lavsoft text-accent hover:bg-lav/40"}`}>
                      <button type="button" onClick={() => choose(f.username)} className="font-semibold">★ {f.username}</button>
                      <button type="button" title="Retirer" onClick={() => act(() => removeFavorite(f.username), "Favori retiré")} className={`ml-1 ${recipient === f.username ? "text-white/70" : "text-ink/40"} hover:text-red-500`}>×</button>
                    </span>
                  ))}
                </div>
              </>
            )}
            <label className="block text-sm font-semibold mb-1">Rechercher un ami</label>
            <input value={q} onChange={(e) => doSearch(e.target.value)} placeholder="Nom…" className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
            {results.length > 0 && <div className="flex flex-wrap gap-2 mt-2">{results.map((u) => <button key={u.username} onClick={() => choose(u.username)} className="text-sm bg-lavsoft text-accent px-3 py-1 rounded-full hover:bg-lav/40">{u.username}</button>)}</div>}
            {recipient && (
              <div className="text-sm mt-2 flex items-center gap-2">
                <span>Destinataire : <b>{recipient}</b></span>
                {isFav ? <button onClick={() => act(() => removeFavorite(recipient), "Favori retiré")} className="text-xs text-ink/50 hover:text-red-500">★ retirer</button>
                  : <button onClick={() => act(() => addFavorite(recipient), "Ajouté aux favoris")} className="text-xs text-accent hover:underline">☆ ajouter aux favoris</button>}
              </div>
            )}
            <label className="block text-sm font-semibold mb-1 mt-4">Montant (€)</label>
            <input type="number" min="1" step="1" value={payAmount} onChange={(e) => setPayAmount(e.target.value)} className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
            <button onClick={doPay} className="mt-4 bg-accent text-white font-semibold px-5 py-2.5 rounded-lg hover:bg-ink transition">{recipient ? `Payer ${recipient}` : "Payer"}</button>
          </div>
          <div className="bg-white rounded-2xl shadow p-5">
            <h2 className="font-bold text-lg text-ink mb-3">Historique</h2>
            {txs.length === 0 ? <p className="text-sm text-ink/50">Aucune transaction.</p> : (
              <div className="divide-y divide-lavsoft max-h-[28rem] overflow-auto">
                {txs.map((t) => (
                  <div key={t.id} className="flex items-center justify-between py-2 text-sm">
                    <span>{t.type === "credit" ? "↓ reçu" : "↑ envoyé"} <span className="text-ink/50">{t.recipient}</span></span>
                    <span className={t.type === "credit" ? "text-green-700 font-semibold" : "font-semibold"}>{t.type === "credit" ? "+" : "−"}{euro(t.amount)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* CASINO */}
      {tab === "casino" && <Casino onBalance={refresh} />}

      {/* CLASSEMENT */}
      {tab === "classement" && (
        <div className="bg-white rounded-2xl shadow overflow-hidden">
          <div className="px-4 py-3 border-b border-lavsoft font-bold text-ink">🏁 Course au milliard</div>
          {lb.board.map((b, i) => (
            <div key={b.name} className={`flex items-center gap-3 px-4 py-2.5 border-b border-lavsoft ${b.name === me ? "bg-lavsoft" : ""}`}>
              <span className={`w-7 text-center font-black ${i === 0 ? "text-amber-500" : "text-ink/40"}`}>{i + 1}</span>
              <span className="font-semibold text-ink">{b.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${b.camp === "attaquant" ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>{b.camp}</span>
              <span className="ml-auto font-mono font-bold text-ink">{euro(b.networth)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Widgets flottants (toutes les pages) */}
      <ChatWidget />
      <DinoWidget onEarned={refresh} />
    </div>
  );
}
