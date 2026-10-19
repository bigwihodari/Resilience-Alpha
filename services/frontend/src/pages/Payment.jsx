import { useEffect, useState } from "react";
import { getAccount, createTx, listTx } from "../api.js";

export default function Payment() {
  const [account, setAccount] = useState(null);
  const [txs, setTxs] = useState([]);
  const [amount, setAmount] = useState("50");
  const [recipient, setRecipient] = useState("MERCHANT-01");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [acc, list] = await Promise.all([getAccount(), listTx()]);
      setAccount(acc);
      setTxs(list);
    } catch (e) {
      setMsg({ type: "err", text: e.message });
    }
  }

  useEffect(() => { refresh(); }, []);

  async function pay(e) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await createTx(parseFloat(amount), recipient);
      setMsg({ type: "ok", text: `Paiement #${r.id} validé — nouveau solde ${r.new_balance} €` });
      await refresh();
    } catch (e) {
      setMsg({ type: "err", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-5">
      <div className="bg-gradient-to-br from-ink to-accent text-white rounded-2xl p-6 shadow-lg mb-6">
        <div className="text-sm opacity-80">Solde du compte</div>
        <div className="text-4xl font-extrabold mt-1">
          {account ? `${account.balance.toLocaleString("fr-FR")} ${account.currency}` : "…"}
        </div>
        <div className="text-sm opacity-70 mt-1">Titulaire : {account?.username ?? "…"}</div>
      </div>

      <form onSubmit={pay} className="bg-white rounded-2xl shadow p-6 mb-6">
        <h2 className="font-bold text-lg mb-4">Nouveau paiement</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-semibold mb-1">Montant (€)</label>
            <input type="number" min="1" step="1" value={amount} onChange={(e) => setAmount(e.target.value)}
              className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
          </div>
          <div>
            <label className="block text-sm font-semibold mb-1">Bénéficiaire</label>
            <input value={recipient} onChange={(e) => setRecipient(e.target.value)}
              className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent" />
          </div>
        </div>
        <button disabled={busy}
          className="mt-4 bg-accent text-white font-semibold px-5 py-2.5 rounded-lg hover:bg-ink transition disabled:opacity-50">
          {busy ? "Envoi…" : "Payer"}
        </button>
        {msg && (
          <div className={`mt-3 text-sm ${msg.type === "ok" ? "text-green-700" : "text-red-600"}`}>{msg.text}</div>
        )}
      </form>

      <div className="bg-white rounded-2xl shadow p-6">
        <h2 className="font-bold text-lg mb-4">Historique</h2>
        {txs.length === 0 ? (
          <p className="text-sm text-ink/50">Aucune transaction.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-ink/60 border-b border-lavsoft">
                <th className="py-2">#</th><th>Montant</th><th>Bénéficiaire</th><th>Statut</th><th>Date</th>
              </tr>
            </thead>
            <tbody>
              {txs.map((t) => (
                <tr key={t.id} className="border-b border-lavsoft/60">
                  <td className="py-2">{t.id}</td>
                  <td>{t.amount} €</td>
                  <td>{t.recipient}</td>
                  <td>
                    <span className={t.status === "completed" ? "text-green-700" : "text-red-600"}>{t.status}</span>
                  </td>
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
