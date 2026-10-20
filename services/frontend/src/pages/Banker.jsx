import { useEffect, useRef, useState } from "react";
import {
  bankAccounts, bankTransactions, bankCredit, bankDebit,
} from "../api.js";

const euro = (n) => `${Number(n).toLocaleString("fr-FR", { minimumFractionDigits: 2 })} €`;

export default function Banker() {
  const [data, setData] = useState({ accounts: [], count: 0, total_balance: 0 });
  const [selected, setSelected] = useState(null);     // username du client sélectionné
  const [history, setHistory] = useState([]);
  const [amount, setAmount] = useState("100");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState(false);
  const selectedRef = useRef(null);
  selectedRef.current = selected;

  async function refreshAccounts() {
    try { setData(await bankAccounts()); }
    catch (e) { setMsg({ type: "err", text: e.message }); }
  }
  async function refreshHistory(username) {
    const u = username ?? selectedRef.current;
    if (!u) { setHistory([]); return; }
    try { setHistory(await bankTransactions(u)); }
    catch (e) { setMsg({ type: "err", text: e.message }); }
  }

  useEffect(() => {
    refreshAccounts();
    // Temps réel : chaque mouvement (paiement client ou opération banquier)
    // rafraîchit la liste des comptes et l'historique affiché — sans refresh manuel.
    let ws, stopped = false, retry;
    const connect = () => {
      try {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        ws = new WebSocket(`${proto}://${location.host}/ws`);
        ws.onopen = () => setLive(true);
        ws.onmessage = (e) => {
          try {
            if (JSON.parse(e.data).type === "tx") {
              refreshAccounts();
              refreshHistory();
            }
          } catch { /* */ }
        };
        ws.onclose = () => { setLive(false); if (!stopped) retry = setTimeout(connect, 2000); };
        ws.onerror = () => { try { ws.close(); } catch { /* */ } };
      } catch { retry = setTimeout(connect, 2000); }
    };
    connect();
    return () => { stopped = true; clearTimeout(retry); try { ws && ws.close(); } catch { /* */ } };
  }, []);

  function select(username) {
    setSelected(username);
    setMsg(null);
    refreshHistory(username);
  }

  async function op(kind) {
    if (!selected) { setMsg({ type: "err", text: "Sélectionne un compte client." }); return; }
    const a = parseFloat(amount);
    if (!Number.isFinite(a) || a <= 0) { setMsg({ type: "err", text: "Montant invalide." }); return; }
    setBusy(true); setMsg(null);
    try {
      const fn = kind === "credit" ? bankCredit : bankDebit;
      const r = await fn(selected, a, note || undefined);
      setMsg({
        type: "ok",
        text: `${kind === "credit" ? "Crédit" : "Retrait"} de ${euro(a)} sur ${selected} — nouveau solde ${euro(r.new_balance)}`,
      });
      setNote("");
      await Promise.all([refreshAccounts(), refreshHistory(selected)]);
    } catch (e) {
      setMsg({ type: "err", text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-6xl mx-auto p-5">
      {/* En-tête + KPI */}
      <div className="flex items-center gap-3 mb-5">
        <h1 className="text-2xl font-extrabold text-ink">Interface banquier</h1>
        <span className={`text-xs px-2 py-0.5 rounded-full ${live ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-500"}`}>
          {live ? "● temps réel" : "○ hors ligne"}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
        <div className="bg-gradient-to-br from-ink to-accent text-white rounded-2xl p-5 shadow">
          <div className="text-sm opacity-80">Masse monétaire</div>
          <div className="text-3xl font-extrabold mt-1">{euro(data.total_balance)}</div>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow">
          <div className="text-sm text-ink/60">Comptes clients</div>
          <div className="text-3xl font-extrabold text-ink mt-1">{data.count}</div>
        </div>
        <div className="bg-white rounded-2xl p-5 shadow hidden sm:block">
          <div className="text-sm text-ink/60">Compte sélectionné</div>
          <div className="text-2xl font-bold text-accent mt-1 truncate">{selected || "—"}</div>
        </div>
      </div>

      {msg && (
        <div className={`rounded-lg px-4 py-2 mb-5 text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
          {msg.text}
        </div>
      )}

      <div className="grid md:grid-cols-5 gap-6">
        {/* Liste des comptes */}
        <div className="md:col-span-2 bg-white rounded-2xl shadow overflow-hidden">
          <div className="px-4 py-3 border-b border-lavsoft font-bold text-ink">Comptes clients</div>
          <div className="max-h-[28rem] overflow-y-auto">
            {data.accounts.length === 0 && (
              <div className="px-4 py-6 text-sm text-ink/50">Aucun compte.</div>
            )}
            {data.accounts.map((a) => (
              <button
                key={a.username}
                onClick={() => select(a.username)}
                className={`w-full flex items-center justify-between px-4 py-3 border-b border-lavsoft text-left hover:bg-lavsoft transition ${selected === a.username ? "bg-lavsoft" : ""}`}
              >
                <span className="font-semibold text-ink">{a.username}</span>
                <span className="text-right">
                  <span className="font-mono text-ink/80 block">{euro(a.balance)}</span>
                  {a.savings > 0 && <span className="font-mono text-[11px] text-green-600 block">livret {euro(a.savings)}</span>}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Détail : opérations + historique */}
        <div className="md:col-span-3 space-y-6">
          <div className="bg-white rounded-2xl shadow p-5">
            <div className="font-bold text-ink mb-3">
              Opération {selected ? <>sur <span className="text-accent">{selected}</span></> : ""}
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs font-semibold text-ink/60 mb-1">Montant (€)</label>
                <input
                  type="number" min="0" step="0.01" value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="w-32 border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <div className="flex-1 min-w-[10rem]">
                <label className="block text-xs font-semibold text-ink/60 mb-1">Motif (optionnel)</label>
                <input
                  value={note} onChange={(e) => setNote(e.target.value)}
                  placeholder="ex. dépôt espèces"
                  className="w-full border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent"
                />
              </div>
              <button
                disabled={busy || !selected}
                onClick={() => op("credit")}
                className="bg-green-600 text-white font-semibold px-4 py-2 rounded-lg hover:bg-green-700 transition disabled:opacity-40"
              >
                Créditer
              </button>
              <button
                disabled={busy || !selected}
                onClick={() => op("debit")}
                className="bg-accent text-white font-semibold px-4 py-2 rounded-lg hover:bg-ink transition disabled:opacity-40"
              >
                Débiter
              </button>
            </div>
          </div>

          <div className="bg-white rounded-2xl shadow overflow-hidden">
            <div className="px-4 py-3 border-b border-lavsoft font-bold text-ink">
              Historique {selected ? `— ${selected}` : ""}
            </div>
            <div className="max-h-[22rem] overflow-y-auto">
              {!selected && <div className="px-4 py-6 text-sm text-ink/50">Sélectionne un compte pour voir ses mouvements.</div>}
              {selected && history.length === 0 && <div className="px-4 py-6 text-sm text-ink/50">Aucun mouvement.</div>}
              {history.map((t) => {
                const credit = t.type === "credit";
                return (
                  <div key={t.id} className="flex items-center justify-between px-4 py-2.5 border-b border-lavsoft text-sm">
                    <div>
                      <span className={`font-semibold ${credit ? "text-green-600" : "text-ink"}`}>
                        {credit ? "Crédit" : "Débit"}
                      </span>
                      <span className="text-ink/50 ml-2">{t.recipient || "—"}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-ink/40 text-xs">
                        {t.created_at ? new Date(t.created_at).toLocaleString("fr-FR") : ""}
                      </span>
                      <span className={`font-mono font-semibold ${credit ? "text-green-600" : "text-red-600"}`}>
                        {credit ? "+" : "−"}{euro(t.amount)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
