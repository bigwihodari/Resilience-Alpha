import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getUser, clearSession,
  getNetworth, getLeaderboard,
  getLivrets, createLivret, livretDeposit, livretWithdraw, livretUpgrade, savingsUpgrade,
  savingsDeposit, savingsWithdraw,
  getShop, shopBuy,
  getMail, markMailRead, getAuctions, bidAuction, getQuizzes, answerQuiz,
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
  const [openMail, setOpenMail] = useState(null);
  const [auctions, setAuctions] = useState([]);
  const [quizzes, setQuizzes] = useState([]);
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
      listTx().catch(() => []), listFavorites().catch(() => []),
    ]);
    if (n) setNw(n); if (l) setLb(l); if (lv) setLiv(lv); if (sh) setShop(sh);
    setMail(mb || []); setAuctions(au || []); setQuizzes(qz || []); setTxs(tx || []); setFavs(fv || []);
  }

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, 5000);
    let ws, stopped = false, retry, ping;
    const connect = () => {
      try {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws`);
        ws.onopen = () => { clearInterval(ping); ping = setInterval(() => { try { ws.send("ping"); } catch { /* */ } }, 25000); };
        ws.onmessage = (e) => { try { const d = JSON.parse(e.data); if (["tx", "win", "mail", "auction", "quiz"].includes(d.type)) refresh(); } catch { /* */ } };
        ws.onclose = () => { clearInterval(ping); if (!stopped) retry = setTimeout(connect, 2000); };
        ws.onerror = () => { try { ws.close(); } catch { /* */ } };
      } catch { retry = setTimeout(connect, 2000); }
    };
    connect();
    return () => { stopped = true; clearInterval(poll); clearInterval(retry); clearInterval(ping); try { ws && ws.close(); } catch { /* */ } };
  }, []);

  async function act(fn, ok) { try { const r = await fn(); flash(typeof ok === "function" ? ok(r) : ok); await refresh(); } catch (e) { flash(e.message, "err"); } }

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
    setOpenMail(openMail === m.id ? null : m.id);
    if (!m.is_read) { try { await markMailRead(m.id); await refresh(); } catch { /* */ } }
  }

  const progress = nw ? Math.min(100, (nw.networth / nw.target) * 100) : 0;
  const myRank = lb.board.findIndex((b) => b.name === me) + 1;
  const unread = mail.filter((m) => !m.is_read).length;
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
        <div className="text-xs opacity-80 mt-1">{progress.toFixed(2)} % vers le million</div>
      </div>

      {lb.winner && <div className="bg-amber-400 text-ink rounded-2xl p-4 mb-4 text-center font-extrabold shadow-lg animate-pulse">🏆 VICTOIRE — {lb.winner.name} ({lb.winner.camp}) a atteint le million !</div>}

      {/* Menu (onglets) — collant en haut au défilement */}
      <div role="tablist" aria-label="Navigation" className="sticky top-0 z-30 flex gap-2 overflow-x-auto py-2 mb-4 -mx-4 px-4 bg-[#E4E6F3]/85 backdrop-blur">
        <TabBtn id="livrets" label="💰 Livrets & Shop" />
        <TabBtn id="marche" label="📬 Marché" badge={unread || null} />
        <TabBtn id="payer" label="💸 Payer" />
        <TabBtn id="casino" label="🎰 Casino" />
        <TabBtn id="classement" label="🏁 Classement" />
      </div>

      {toast && <div className={`fixed bottom-24 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl shadow-lg text-sm font-semibold ${toast.type === "ok" ? "bg-green-600 text-white" : "bg-red-600 text-white"}`}>{toast.text}</div>}

      {/* LIVRETS & SHOP */}
      {tab === "livrets" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="space-y-3">
            <div className="bg-white rounded-2xl shadow p-4">
              <div className="flex items-center justify-between">
                <div className="font-bold text-ink">Livret principal <span className="text-xs text-ink/40">niv {liv.principal.level || 0}</span></div>
                <div className="text-xs text-green-600 font-semibold">+{((liv.principal.rate || 0) * 100).toFixed(2)} % / {liv.interval}s</div>
              </div>
              <div className="text-3xl font-extrabold text-green-700 mt-1">{euro(liv.principal.balance)}</div>
              <div className="flex flex-wrap gap-2 mt-2">
                <button onClick={() => act(() => savingsDeposit(100), "Dépôt de 100 €")} className="text-xs bg-green-600 text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-green-700">Déposer 100</button>
                <button onClick={() => act(() => savingsWithdraw(100), "Retrait de 100 €")} className="text-xs bg-ink text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-accent">Retirer 100</button>
                <button onClick={() => act(() => savingsUpgrade(), (r) => `Taux boosté à +${(r.rate * 100).toFixed(2)} %`)} className="text-xs bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">⬆ Booster ({euro(liv.principal.upgrade_cost || 0)})</button>
              </div>
            </div>
            {liv.livrets.map((lv) => (
              <div key={lv.id} className="bg-white rounded-2xl shadow p-4">
                <div className="flex items-center justify-between">
                  <div className="font-bold text-ink">{lv.name} <span className="text-xs text-ink/40">niv {lv.level}</span></div>
                  <div className="text-xs text-green-600 font-semibold">+{(lv.rate * 100).toFixed(2)} % / {liv.interval}s</div>
                </div>
                <div className="text-2xl font-extrabold text-green-700 mt-1">{euro(lv.balance)}</div>
                <div className="flex flex-wrap gap-2 mt-2">
                  <button onClick={() => act(() => livretDeposit(lv.id, 100), "Dépôt de 100 €")} className="text-xs bg-green-600 text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-green-700">Déposer 100</button>
                  <button onClick={() => act(() => livretWithdraw(lv.id, 100), "Retrait de 100 €")} className="text-xs bg-ink text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-accent">Retirer 100</button>
                  <button onClick={() => act(() => livretUpgrade(lv.id), (r) => `Taux boosté à +${(r.rate * 100).toFixed(2)} %`)} className="text-xs bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">⬆ Booster ({euro(lv.upgrade_cost)})</button>
                </div>
              </div>
            ))}
            <button onClick={() => act(() => createLivret(), "Nouveau livret ouvert")} className="w-full bg-white border-2 border-dashed border-lav text-accent font-semibold py-2.5 rounded-2xl hover:bg-lavsoft">+ Ouvrir un livret</button>
          </div>
          <div className="bg-white rounded-2xl shadow p-4 h-fit">
            <div className="font-bold text-ink mb-3">🛒 Boutique</div>
            <div className="space-y-2">
              {shop.items.map((it) => (
                <div key={it.ukey} className="flex items-center gap-3 border-b border-lavsoft pb-2">
                  <div className="flex-1"><div className="font-semibold text-sm text-ink">{it.label} <span className="text-xs text-ink/40">niv {it.level}</span></div><div className="text-xs text-ink/50">{it.desc}</div></div>
                  <button onClick={() => act(() => shopBuy(it.ukey), (r) => `${it.label} niv ${r.level}`)} className="text-xs bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink whitespace-nowrap">{euro(it.next_cost)}</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* MARCHE */}
      {tab === "marche" && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="space-y-3">
            <div className="font-bold text-accent text-sm uppercase tracking-wide">Enchères</div>
            {auctions.filter((a) => a.status === "open").length === 0 && <div className="text-sm text-ink/50">Aucune enchère en cours.</div>}
            {auctions.filter((a) => a.status === "open").map((a) => (
              <div key={a.id} className="bg-white rounded-2xl shadow p-4">
                <div className="font-bold text-ink">{a.title}</div>
                <div className="text-sm text-ink/60">Valeur {euro(a.item_value)} · mise min {euro(a.min_bid)}</div>
                <div className="flex gap-2 mt-2 items-center">
                  <input id={`bid-${a.id}`} type="number" defaultValue={a.min_bid || 50} className="w-24 border border-lav rounded-lg px-2 py-1.5 text-sm" />
                  <button onClick={() => act(() => bidAuction(a.id, parseFloat(document.getElementById(`bid-${a.id}`).value)), "Enchère placée")} className="text-sm bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">Enchérir</button>
                </div>
              </div>
            ))}
            <div className="font-bold text-accent text-sm uppercase tracking-wide mt-4">Quiz</div>
            {quizzes.filter((q) => q.status === "open").length === 0 && <div className="text-sm text-ink/50">Aucun quiz en cours.</div>}
            {quizzes.filter((q) => q.status === "open").map((q) => (
              <div key={q.id} className="bg-white rounded-2xl shadow p-4">
                <div className="font-semibold text-ink">{q.question}</div>
                <div className="text-xs text-green-600 font-semibold">Lot : {euro(q.prize)}</div>
                <div className="flex gap-2 mt-2 items-center">
                  <input id={`q-${q.id}`} className="flex-1 border border-lav rounded-lg px-2 py-1.5 text-sm" placeholder="Ta réponse…" />
                  <button onClick={() => act(() => answerQuiz(q.id, document.getElementById(`q-${q.id}`).value), "Réponse envoyée")} className="text-sm bg-accent text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-ink">Répondre</button>
                </div>
              </div>
            ))}
          </div>
          <div>
            <div className="font-bold text-accent text-sm uppercase tracking-wide mb-2">Boîte mail</div>
            <div className="bg-white rounded-2xl shadow divide-y divide-lavsoft max-h-[32rem] overflow-auto">
              {mail.length === 0 && <div className="p-4 text-sm text-ink/50">Aucun message.</div>}
              {mail.map((m) => (
                <button key={m.id} onClick={() => openMailItem(m)} className={`w-full text-left p-3 hover:bg-lavsoft/60 transition ${m.is_read ? "" : "bg-lavsoft/40"}`}>
                  <div className="flex items-center gap-2">
                    {!m.is_read && <span className="w-2 h-2 rounded-full bg-accent shrink-0"></span>}
                    <span className="font-semibold text-sm text-ink">{m.subject}</span>
                    <span className="ml-auto text-[10px] text-ink/40">{m.kind}</span>
                  </div>
                  {openMail === m.id && <div className="text-xs text-ink/70 mt-1.5 whitespace-pre-wrap">{m.body}</div>}
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
          <div className="px-4 py-3 border-b border-lavsoft font-bold text-ink">🏁 Course au million</div>
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
