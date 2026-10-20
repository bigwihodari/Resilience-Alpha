import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getAccount, listTx, searchUsers, pay, getUser, clearSession,
  listFavorites, addFavorite, removeFavorite,
  getSavings, savingsDeposit, savingsWithdraw,
} from "../api.js";

const euro = (n) => `${Number(n).toLocaleString("fr-FR", { minimumFractionDigits: 2 })} €`;

export default function Pay() {
  const [account, setAccount] = useState(null);
  const [txs, setTxs] = useState([]);
  const [favs, setFavs] = useState([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [recipient, setRecipient] = useState("");
  const [amount, setAmount] = useState("20");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  // Livret d'epargne
  const [sav, setSav] = useState({ savings: 0, rate: 0, interval: 30 });
  const [savAmount, setSavAmount] = useState("50");
  const [savMsg, setSavMsg] = useState(null);
  const [savBusy, setSavBusy] = useState(false);
  const me = getUser();
  const nav = useNavigate();

  async function refresh() {
    try {
      const [acc, list, fv, sv] = await Promise.all([getAccount(), listTx(), listFavorites(), getSavings()]);
      setAccount(acc); setTxs(list); setFavs(fv); setSav(sv);
    } catch (e) { setMsg({ type: "err", text: e.message }); }
  }
  useEffect(() => {
    refresh();
    // Temps réel : à chaque transaction poussée par le serveur, on rafraîchit (sans refresh manuel).
    let ws, stopped = false, retry, ping;
    const connect = () => {
      try {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws`);
        // Ping régulier : garde la socket vivante à travers un NAT/WSL qui coupe
        // les connexions longues inactives (sinon les mises à jour live s'arrêtent).
        ws.onopen = () => { clearInterval(ping); ping = setInterval(() => { try { ws.send("ping"); } catch { /* */ } }, 25000); };
        ws.onmessage = (e) => { try { if (JSON.parse(e.data).type === "tx") refresh(); } catch { /* */ } };
        ws.onclose = () => { clearInterval(ping); if (!stopped) retry = setTimeout(connect, 2000); }; // reconnexion (ex. bascule)
        ws.onerror = () => { try { ws.close(); } catch { /* */ } };
      } catch { retry = setTimeout(connect, 2000); }
    };
    connect();
    return () => { stopped = true; clearTimeout(retry); clearInterval(ping); try { ws && ws.close(); } catch { /* */ } };
  }, []);

  async function doSearch(v) {
    setQ(v);
    if (v.trim().length < 1) { setResults([]); return; }
    setResults(await searchUsers(v.trim()));
  }

  function choose(username) { setRecipient(username); setQ(username); setResults([]); }

  async function star(username) {
    try { await addFavorite(username); setFavs(await listFavorites()); }
    catch (e) { setMsg({ type: "err", text: e.message }); }
  }
  async function unstar(username) {
    try { await removeFavorite(username); setFavs(await listFavorites()); }
    catch { /* */ }
  }

  async function doPay(e) {
    e.preventDefault();
    if (!recipient) { setMsg({ type: "err", text: "Choisis un destinataire." }); return; }
    setBusy(true); setMsg({ type: "info", text: "Paiement en cours…" });
    try {
      const r = await pay(recipient, parseFloat(amount),
        (n) => setMsg({ type: "info", text: `Serveur indisponible — reprise de la transaction (essai ${n})…` }));
      setMsg({ type: "ok", text: `Paiement #${r.id} à ${recipient} ${r.resumed ? "(repris)" : ""} — nouveau solde ${euro(r.new_balance)}` });
      setRecipient(""); setQ(""); setResults([]);
      await refresh();
    } catch (e) { setMsg({ type: "err", text: e.message }); }
    finally { setBusy(false); }
  }

  async function doSavings(kind) {
    const a = parseFloat(savAmount);
    if (!Number.isFinite(a) || a <= 0) { setSavMsg({ type: "err", text: "Montant invalide." }); return; }
    setSavBusy(true); setSavMsg(null);
    try {
      const fn = kind === "deposit" ? savingsDeposit : savingsWithdraw;
      const r = await fn(a);
      setSavMsg({ type: "ok", text: `${kind === "deposit" ? "Dépôt" : "Retrait"} de ${euro(a)} — livret ${euro(r.savings)}` });
      await refresh();
    } catch (e) { setSavMsg({ type: "err", text: e.message }); }
    finally { setSavBusy(false); }
  }

  const isFav = recipient && favs.some((f) => f.username === recipient);
  const ratePct = sav.rate ? +(sav.rate * 100).toFixed(2) : 0;

  return (
    <div className="max-w-2xl mx-auto p-5">
      <div className="flex items-center mb-4">
        <div>
          <div className="text-xs tracking-widest text-accent font-bold">RESILIENCE-ALPHA · CLIENT</div>
          <div className="text-lg font-bold">Bonjour {me}</div>
        </div>
        <button className="ml-auto text-sm bg-white px-3 py-1.5 rounded-lg shadow"
          onClick={() => { clearSession(); nav("/"); }}>Déconnexion</button>
      </div>

      {/* Soldes : courant + livret */}
      <div className="grid sm:grid-cols-2 gap-4 mb-6">
        <div className="bg-gradient-to-br from-ink to-accent text-white rounded-2xl p-6 shadow-lg">
          <div className="text-sm opacity-80">Compte courant</div>
          <div className="text-4xl font-extrabold mt-1">{account ? euro(account.balance) : "…"}</div>
        </div>
        <div className="bg-white rounded-2xl p-6 shadow-lg border-t-4 border-green-500">
          <div className="text-sm text-ink/60">Livret d'épargne {ratePct > 0 && <span className="text-green-600 font-semibold">· +{ratePct}% / {sav.interval}s</span>}</div>
          <div className="text-4xl font-extrabold mt-1 text-green-700">{euro(sav.savings)}</div>
          <div className="flex items-center gap-2 mt-3">
            <input type="number" min="1" step="1" value={savAmount} onChange={(e) => setSavAmount(e.target.value)}
              className="w-24 border border-lav rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-green-500" />
            <button disabled={savBusy} onClick={() => doSavings("deposit")}
              className="text-sm bg-green-600 text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-green-700 disabled:opacity-50">Déposer</button>
            <button disabled={savBusy} onClick={() => doSavings("withdraw")}
              className="text-sm bg-ink text-white font-semibold px-3 py-1.5 rounded-lg hover:bg-accent disabled:opacity-50">Retirer</button>
          </div>
          {savMsg && <div className={`mt-2 text-sm ${savMsg.type === "ok" ? "text-green-700" : "text-red-600"}`}>{savMsg.text}</div>}
        </div>
      </div>

      <form onSubmit={doPay} className="bg-white rounded-2xl shadow p-6 mb-6">
        <h2 className="font-bold text-lg mb-3">Payer</h2>

        {/* Favoris : paiement en un clic */}
        {favs.length > 0 && (
          <>
            <label className="block text-sm font-semibold mb-1">Favoris</label>
            <div className="flex flex-wrap gap-2 mb-4">
              {favs.map((f) => (
                <span key={f.username}
                  className={`inline-flex items-center gap-1 text-sm px-3 py-1 rounded-full cursor-pointer ${recipient === f.username ? "bg-accent text-white" : "bg-lavsoft text-accent hover:bg-lav/40"}`}>
                  <button type="button" onClick={() => choose(f.username)} className="font-semibold">★ {f.username}</button>
                  <button type="button" title="Retirer des favoris" onClick={() => unstar(f.username)}
                    className={`ml-1 ${recipient === f.username ? "text-white/70" : "text-ink/40"} hover:text-red-500`}>×</button>
                </span>
              ))}
            </div>
          </>
        )}

        <label className="block text-sm font-semibold mb-1">Rechercher un ami</label>
        <input value={q} onChange={(e) => doSearch(e.target.value)} placeholder="Nom…"
          className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
        {results.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {results.map((u) => (
              <button type="button" key={u.username} onClick={() => choose(u.username)}
                className="text-sm bg-lavsoft text-accent px-3 py-1 rounded-full hover:bg-lav/40">{u.username}</button>
            ))}
          </div>
        )}
        {recipient && (
          <div className="text-sm mt-2 flex items-center gap-2">
            <span>Destinataire : <b>{recipient}</b></span>
            {isFav ? (
              <button type="button" onClick={() => unstar(recipient)} className="text-xs text-ink/50 hover:text-red-500">★ retirer des favoris</button>
            ) : (
              <button type="button" onClick={() => star(recipient)} className="text-xs text-accent hover:underline">☆ ajouter aux favoris</button>
            )}
          </div>
        )}
        <label className="block text-sm font-semibold mb-1 mt-4">Montant (€)</label>
        <input type="number" min="1" step="1" value={amount} onChange={(e) => setAmount(e.target.value)}
          className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
        <button disabled={busy} className="mt-4 bg-accent text-white font-semibold px-5 py-2.5 rounded-lg hover:bg-ink transition disabled:opacity-50">
          {busy ? "…" : recipient ? `Payer ${recipient}` : "Payer"}
        </button>
        {msg && <div className={`mt-3 text-sm ${msg.type === "ok" ? "text-green-700" : msg.type === "err" ? "text-red-600" : "text-amber-700"}`}>{msg.text}</div>}
      </form>

      <div className="bg-white rounded-2xl shadow p-6">
        <h2 className="font-bold text-lg mb-4">Historique</h2>
        {txs.length === 0 ? <p className="text-sm text-ink/50">Aucune transaction.</p> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-ink/60 border-b border-lavsoft">
              <th className="py-2">Type</th><th>Montant</th><th>Avec</th><th>Date</th></tr></thead>
            <tbody>
              {txs.map((t) => (
                <tr key={t.id} className="border-b border-lavsoft/60">
                  <td className="py-2">{t.type === "credit" ? "↓ reçu" : "↑ envoyé"}</td>
                  <td className={t.type === "credit" ? "text-green-700" : ""}>{t.type === "credit" ? "+" : "−"}{euro(t.amount)}</td>
                  <td>{t.recipient}</td>
                  <td className="text-ink/50">{t.created_at ? new Date(t.created_at).toLocaleString("fr-FR") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
