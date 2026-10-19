import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAccount, listTx, searchUsers, pay, getUser, clearSession } from "../api.js";

export default function Pay() {
  const [account, setAccount] = useState(null);
  const [txs, setTxs] = useState([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [recipient, setRecipient] = useState("");
  const [amount, setAmount] = useState("20");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const me = getUser();
  const nav = useNavigate();

  async function refresh() {
    try {
      const [acc, list] = await Promise.all([getAccount(), listTx()]);
      setAccount(acc); setTxs(list);
    } catch (e) { setMsg({ type: "err", text: e.message }); }
  }
  useEffect(() => { refresh(); }, []);

  async function doSearch(v) {
    setQ(v);
    if (v.trim().length < 1) { setResults([]); return; }
    setResults(await searchUsers(v.trim()));
  }

  async function doPay(e) {
    e.preventDefault();
    if (!recipient) { setMsg({ type: "err", text: "Choisis un destinataire." }); return; }
    setBusy(true); setMsg({ type: "info", text: "Paiement en cours…" });
    try {
      const r = await pay(recipient, parseFloat(amount),
        (n) => setMsg({ type: "info", text: `Serveur indisponible — reprise de la transaction (essai ${n})…` }));
      setMsg({ type: "ok", text: `Paiement #${r.id} à ${recipient} ${r.resumed ? "(repris)" : ""} — nouveau solde ${r.new_balance} €` });
      setRecipient(""); setQ(""); setResults([]);
      await refresh();
    } catch (e) { setMsg({ type: "err", text: e.message }); }
    finally { setBusy(false); }
  }

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

      <div className="bg-gradient-to-br from-ink to-accent text-white rounded-2xl p-6 shadow-lg mb-6">
        <div className="text-sm opacity-80">Solde</div>
        <div className="text-4xl font-extrabold mt-1">{account ? `${account.balance.toLocaleString("fr-FR")} €` : "…"}</div>
      </div>

      <form onSubmit={doPay} className="bg-white rounded-2xl shadow p-6 mb-6">
        <h2 className="font-bold text-lg mb-4">Payer un ami</h2>
        <label className="block text-sm font-semibold mb-1">Rechercher un ami</label>
        <input value={q} onChange={(e) => doSearch(e.target.value)} placeholder="Nom…"
          className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
        {results.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-2">
            {results.map((u) => (
              <button type="button" key={u.username} onClick={() => { setRecipient(u.username); setQ(u.username); setResults([]); }}
                className="text-sm bg-lavsoft text-accent px-3 py-1 rounded-full hover:bg-lav/40">{u.username}</button>
            ))}
          </div>
        )}
        {recipient && <div className="text-sm mt-2">Destinataire : <b>{recipient}</b></div>}
        <label className="block text-sm font-semibold mb-1 mt-4">Montant (€)</label>
        <input type="number" min="1" step="1" value={amount} onChange={(e) => setAmount(e.target.value)}
          className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
        <button disabled={busy} className="mt-4 bg-accent text-white font-semibold px-5 py-2.5 rounded-lg hover:bg-ink transition disabled:opacity-50">
          {busy ? "…" : "Payer"}
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
                  <td className={t.type === "credit" ? "text-green-700" : ""}>{t.type === "credit" ? "+" : "−"}{t.amount} €</td>
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
