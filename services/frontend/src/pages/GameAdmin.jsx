import { useEffect, useRef, useState } from "react";
import {
  leaderboard, bankAuctions, createAuction, closeAuction,
  bankQuizzes, createQuiz, bankIntelOffers, createIntelOffer,
} from "../api.js";

const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} €`;

export default function GameAdmin() {
  const [lb, setLb] = useState({ board: [], target: 1000000, winner: null });
  const [auctions, setAuctions] = useState([]);
  const [quizzes, setQuizzes] = useState([]);
  const [offers, setOffers] = useState([]);
  const [msg, setMsg] = useState(null);
  // formulaires
  const [aTitle, setATitle] = useState(""); const [aVal, setAVal] = useState("1000"); const [aMin, setAMin] = useState("50");
  const [qQ, setQQ] = useState(""); const [qA, setQA] = useState(""); const [qP, setQP] = useState("300");
  const [iT, setIT] = useState(""); const [iP, setIP] = useState("150");
  const timer = useRef(null);

  const flash = (t, type = "ok") => { setMsg({ t, type }); setTimeout(() => setMsg(null), 3000); };
  async function refresh() {
    const [l, a, q, o] = await Promise.all([
      leaderboard().catch(() => null), bankAuctions().catch(() => null),
      bankQuizzes().catch(() => null), bankIntelOffers().catch(() => null),
    ]);
    if (l) setLb(l);
    setAuctions((a && a.auctions) || []); setQuizzes((q && q.quizzes) || []); setOffers((o && o.offers) || []);
  }
  useEffect(() => { refresh(); timer.current = setInterval(refresh, 4000); return () => clearInterval(timer.current); }, []);
  async function act(fn, ok) { try { await fn(); flash(ok); await refresh(); } catch (e) { flash(e.message, "err"); } }

  const Card = ({ title, children }) => (
    <div className="bg-white rounded-2xl shadow p-5">
      <div className="font-bold text-ink mb-3">{title}</div>{children}
    </div>
  );
  const inp = "w-full border border-lav rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent";

  return (
    <div className="max-w-5xl mx-auto p-5">
      <h1 className="text-2xl font-extrabold text-ink mb-1">Animation du jeu</h1>
      <p className="text-sm text-ink/60 mb-5">Banquier : lance des enchères, des quiz, et vends de l'info aux attaquants.</p>
      {msg && <div className={`rounded-lg px-4 py-2 mb-4 text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{msg.t}</div>}

      {/* Leaderboard */}
      <div className="bg-gradient-to-br from-ink to-accent text-white rounded-2xl shadow p-5 mb-5">
        <div className="flex items-center justify-between mb-2">
          <div className="font-bold">🏁 Course au million</div>
          <div className="text-sm opacity-80">Objectif {euro(lb.target)}</div>
        </div>
        {lb.winner && <div className="bg-amber-400 text-ink rounded-lg px-3 py-1.5 mb-2 font-bold text-center">🏆 {lb.winner.name} ({lb.winner.camp}) a gagné !</div>}
        {lb.board.slice(0, 6).map((b, i) => (
          <div key={b.name} className="flex items-center gap-3 py-1 border-b border-white/10 text-sm">
            <span className="w-6 text-center font-black opacity-80">{i + 1}</span>
            <span className="font-semibold">{b.name}</span>
            <span className={`text-[10px] px-2 py-0.5 rounded-full ${b.camp === "attaquant" ? "bg-red-500/40" : "bg-green-500/40"}`}>{b.camp}</span>
            <span className="ml-auto font-mono">{euro(b.networth)}</span>
          </div>
        ))}
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        {/* Enchères */}
        <Card title="🔨 Enchères">
          <div className="space-y-2">
            <input className={inp} placeholder="Objet (ex: Montre en or)" value={aTitle} onChange={(e) => setATitle(e.target.value)} />
            <div className="flex gap-2">
              <input className={inp} type="number" placeholder="Valeur" value={aVal} onChange={(e) => setAVal(e.target.value)} />
              <input className={inp} type="number" placeholder="Mise min" value={aMin} onChange={(e) => setAMin(e.target.value)} />
            </div>
            <button onClick={() => act(() => createAuction(aTitle, +aVal, +aMin), "Enchère lancée")} disabled={!aTitle}
              className="w-full bg-accent text-white font-semibold py-2 rounded-lg hover:bg-ink disabled:opacity-40">Lancer l'enchère</button>
          </div>
          <div className="mt-3 space-y-1 max-h-48 overflow-auto">
            {auctions.filter((a) => a.status === "open").map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-sm border-b border-lavsoft py-1">
                <span className="flex-1 truncate">{a.title} <span className="text-ink/40">({euro(a.item_value)})</span></span>
                <button onClick={() => act(() => closeAuction(a.id), "Enchère clôturée")} className="text-xs bg-ink text-white px-2 py-1 rounded">Clôturer</button>
              </div>
            ))}
          </div>
        </Card>

        {/* Quiz */}
        <Card title="❓ Quiz / concours">
          <div className="space-y-2">
            <input className={inp} placeholder="Question" value={qQ} onChange={(e) => setQQ(e.target.value)} />
            <div className="flex gap-2">
              <input className={inp} placeholder="Réponse" value={qA} onChange={(e) => setQA(e.target.value)} />
              <input className={inp} type="number" placeholder="Lot" value={qP} onChange={(e) => setQP(e.target.value)} />
            </div>
            <button onClick={() => act(() => createQuiz(qQ, qA, +qP), "Quiz lancé")} disabled={!qQ || !qA}
              className="w-full bg-accent text-white font-semibold py-2 rounded-lg hover:bg-ink disabled:opacity-40">Lancer le quiz</button>
          </div>
          <div className="mt-3 space-y-1 max-h-48 overflow-auto">
            {quizzes.filter((q) => q.status === "open").map((q) => (
              <div key={q.id} className="text-sm border-b border-lavsoft py-1 truncate">{q.question} <span className="text-green-600">{euro(q.prize)}</span></div>
            ))}
          </div>
        </Card>

        {/* Intel (insider) */}
        <Card title="🕵️ Vendre de l'info (insider)">
          <div className="space-y-2">
            <input className={inp} placeholder="Client ciblé (ex: bob)" value={iT} onChange={(e) => setIT(e.target.value)} />
            <input className={inp} type="number" placeholder="Prix (payé par l'attaquant)" value={iP} onChange={(e) => setIP(e.target.value)} />
            <button onClick={() => act(() => createIntelOffer(iT, +iP), "Info mise en vente")} disabled={!iT}
              className="w-full bg-red-600 text-white font-semibold py-2 rounded-lg hover:bg-red-700 disabled:opacity-40">Vendre l'info</button>
          </div>
          <div className="mt-3 space-y-1 max-h-48 overflow-auto">
            {offers.map((o) => (
              <div key={o.id} className="text-sm border-b border-lavsoft py-1">cible <b>{o.target}</b> — {euro(o.price)} {o.sold ? <span className="text-ink/40">(vendue)</span> : null}</div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
