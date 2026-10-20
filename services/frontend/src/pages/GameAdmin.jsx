import { useEffect, useRef, useState } from "react";
import {
  leaderboard, bankAuctions, createAuction, closeAuction,
  bankQuizzes, createQuiz, bankIntelOffers, createIntelOffer,
} from "../api.js";

const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} €`;

const SPECIALS = [
  { key: "sp_prod", label: "⚡ Turbo production" },
  { key: "sp_interest", label: "📈 Taux privilégié" },
  { key: "sp_discount", label: "🏷️ Remise VIP" },
];
const perkColor = (k) => k === "upgrade" ? "bg-fuchsia-100 text-fuchsia-700" : k === "pct" ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700";

export default function GameAdmin() {
  const [lb, setLb] = useState({ board: [], target: 1000000, winner: null });
  const [auctions, setAuctions] = useState([]);
  const [quizzes, setQuizzes] = useState([]);
  const [offers, setOffers] = useState([]);
  const [msg, setMsg] = useState(null);
  const [now, setNow] = useState(Date.now());
  const loadedAt = useRef(Date.now());
  // formulaire enchère bonus
  const [aTitle, setATitle] = useState("Lot exceptionnel");
  const [aKind, setAKind] = useState("money");
  const [aVal, setAVal] = useState("5000");     // montant € (money) / % (pct) / équiv. cash (upgrade)
  const [aUpg, setAUpg] = useState("sp_prod");
  const [aMin, setAMin] = useState("500");
  const [aDur, setADur] = useState("90");
  // formulaire quiz
  const [qQ, setQQ] = useState(""); const [qA, setQA] = useState(""); const [qP, setQP] = useState("3000");
  // formulaire intel
  const [iT, setIT] = useState(""); const [iP, setIP] = useState("250");
  const timer = useRef(null);

  const flash = (t, type = "ok") => { setMsg({ t, type }); setTimeout(() => setMsg(null), 3000); };
  async function refresh() {
    const [l, a, q, o] = await Promise.all([
      leaderboard().catch(() => null), bankAuctions().catch(() => null),
      bankQuizzes().catch(() => null), bankIntelOffers().catch(() => null),
    ]);
    if (l) setLb(l);
    setAuctions((a && a.auctions) || []); setQuizzes((q && q.quizzes) || []); setOffers((o && o.offers) || []);
    loadedAt.current = Date.now();
  }
  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 4000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(timer.current); clearInterval(tick); };
  }, []);
  async function act(fn, ok) { try { await fn(); flash(ok); await refresh(); } catch (e) { flash(e.message, "err"); } }
  const secLeft = (x) => x.seconds_left == null ? null : Math.max(0, Math.round(x.seconds_left - (now - loadedAt.current) / 1000));

  function launchAuction() {
    const v = Math.max(1, parseFloat(aVal) || 0);
    const min = Math.max(0, parseFloat(aMin) || 0);
    const dur = Math.max(15, parseFloat(aDur) || 90);
    let item_value = v, perk_value = String(v);
    if (aKind === "pct") { item_value = Math.round(v * 700); perk_value = String(v); }
    if (aKind === "upgrade") { item_value = v; perk_value = aUpg; }
    return act(() => createAuction(aTitle, item_value, min, aKind, perk_value, dur), "Enchère bonus lancée");
  }

  const inp = "w-full border border-lav rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent";
  const Card = ({ title, sub, children }) => (
    <div className="bg-white rounded-2xl shadow p-5">
      <div className="font-bold text-ink">{title}</div>
      {sub && <div className="text-xs text-ink/50 mb-3">{sub}</div>}
      <div className={sub ? "" : "mt-3"}>{children}</div>
    </div>
  );

  const openAuctions = auctions.filter((a) => a.status === "open" && !a.phish);
  const openQuizzes = quizzes.filter((q) => q.status === "open");

  return (
    <div className="max-w-6xl mx-auto p-5">
      {/* Hero */}
      <div className="bg-gradient-to-br from-ink via-accent to-[#6C5CE7] text-white rounded-3xl p-6 shadow-xl mb-5">
        <div className="text-[11px] tracking-widest font-bold opacity-80">RESILIENCE-ALPHA · ANIMATION</div>
        <h1 className="text-3xl font-black mt-1">Salle des marchés</h1>
        <p className="text-sm opacity-85 mt-1 max-w-2xl">
          L'économie tourne toute seule : enchères et quiz s'enchaînent automatiquement (prix de base + timer).
          Toi, tu mets l'ambiance — lance des <b>événements bonus</b>, des quiz maison, et vends de l'info aux attaquants.
        </p>
        <div className="flex gap-2 mt-3 flex-wrap">
          <span className="text-xs font-semibold bg-white/15 px-3 py-1 rounded-full">🔨 {openAuctions.length} enchère(s) en direct</span>
          <span className="text-xs font-semibold bg-white/15 px-3 py-1 rounded-full">🧠 {openQuizzes.length} quiz en direct</span>
          <span className="text-xs font-semibold bg-white/15 px-3 py-1 rounded-full">🎯 Objectif {euro(lb.target)}</span>
        </div>
      </div>

      {msg && <div className={`rounded-xl px-4 py-2 mb-4 text-sm font-semibold ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>{msg.t}</div>}

      {/* Leaderboard */}
      <div className="bg-white rounded-2xl shadow p-5 mb-5">
        <div className="flex items-center justify-between mb-3">
          <div className="font-bold text-ink">🏁 Course au million</div>
          {lb.winner && <span className="bg-amber-400 text-ink rounded-full px-3 py-1 font-bold text-sm">🏆 {lb.winner.name} ({lb.winner.camp}) a gagné !</span>}
        </div>
        {lb.board.slice(0, 6).map((b, i) => {
          const pct = Math.min(100, (b.networth / (lb.target || 1)) * 100);
          return (
            <div key={b.name} className="flex items-center gap-3 py-1.5 text-sm">
              <span className={`w-6 text-center font-black ${i === 0 ? "text-amber-500" : "text-ink/40"}`}>{i + 1}</span>
              <span className="font-semibold text-ink w-28 truncate">{b.name}</span>
              <span className={`text-[10px] px-2 py-0.5 rounded-full ${b.camp === "attaquant" ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`}>{b.camp}</span>
              <div className="flex-1 h-2.5 bg-lavsoft rounded-full overflow-hidden">
                <div className={`h-full ${b.camp === "attaquant" ? "bg-red-500" : "bg-green-500"}`} style={{ width: `${Math.max(2, pct)}%` }} />
              </div>
              <span className="w-28 text-right font-mono font-bold text-ink">{euro(b.networth)}</span>
            </div>
          );
        })}
        {lb.board.length === 0 && <div className="text-sm text-ink/50">Aucun joueur pour l'instant.</div>}
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        {/* ====== ENCHÈRES ====== */}
        <div className="space-y-5">
          <Card title="🔨 Enchères en direct" sub="Générées automatiquement — tu peux clôturer plus tôt.">
            <div className="space-y-2 max-h-72 overflow-auto">
              {openAuctions.length === 0 && <div className="text-sm text-ink/50">Aucune enchère ouverte.</div>}
              {openAuctions.map((a) => {
                const sl = secLeft(a);
                return (
                  <div key={a.id} className="border border-lavsoft rounded-xl p-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-sm text-ink">{a.title}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${perkColor(a.perk_kind)}`}>🎁 {a.perk_label}</span>
                      {a.auto && <span className="text-[10px] text-ink/40">auto</span>}
                      {sl != null && <span className={`ml-auto text-[11px] font-mono font-bold px-2 py-0.5 rounded-full ${sl <= 10 ? "bg-red-100 text-red-700" : "bg-lavsoft text-accent"}`}>⏳ {sl}s</span>}
                    </div>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className="text-xs text-ink/55">
                        min {euro(a.min_bid)} · {(a.bids || []).length} mise(s)
                        {a.highest_bid != null && <> · top <b className="text-ink">{euro(a.highest_bid)}</b></>}
                      </span>
                      <button onClick={() => act(() => closeAuction(a.id), "Enchère clôturée")} className="ml-auto text-xs bg-ink text-white px-2.5 py-1 rounded-lg hover:bg-accent">Clôturer</button>
                    </div>
                    {(a.bids || []).length > 0 && (
                      <div className="text-[11px] text-ink/50 mt-1 truncate">
                        {a.bids.slice(0, 3).map((b) => `${b.username}${b.kind === "attacker" ? " 🦹" : ""} ${euro(b.amount)}`).join(" · ")}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          <Card title="✨ Lancer une enchère bonus">
            <div className="space-y-2">
              <input className={inp} placeholder="Nom du lot" value={aTitle} onChange={(e) => setATitle(e.target.value)} />
              <div className="flex gap-2">
                <select className={inp} value={aKind} onChange={(e) => setAKind(e.target.value)}>
                  <option value="money">💰 Cash</option>
                  <option value="pct">📊 % de fortune</option>
                  <option value="upgrade">✨ Upgrade spéciale</option>
                </select>
                {aKind === "upgrade" ? (
                  <select className={inp} value={aUpg} onChange={(e) => setAUpg(e.target.value)}>
                    {SPECIALS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                ) : (
                  <input className={inp} type="number" placeholder={aKind === "pct" ? "pourcentage" : "montant €"} value={aVal} onChange={(e) => setAVal(e.target.value)} />
                )}
              </div>
              {aKind === "upgrade" && <input className={inp} type="number" placeholder="équivalent cash € (pour attaquants)" value={aVal} onChange={(e) => setAVal(e.target.value)} />}
              <div className="flex gap-2">
                <input className={inp} type="number" placeholder="mise min €" value={aMin} onChange={(e) => setAMin(e.target.value)} />
                <input className={inp} type="number" placeholder="durée (s)" value={aDur} onChange={(e) => setADur(e.target.value)} />
              </div>
              <button onClick={launchAuction} disabled={!aTitle}
                className="w-full bg-accent text-white font-semibold py-2 rounded-lg hover:bg-ink disabled:opacity-40">Lancer l'enchère bonus</button>
            </div>
          </Card>
        </div>

        {/* ====== QUIZ + INTEL ====== */}
        <div className="space-y-5">
          <Card title="🧠 Quiz en direct" sub="Générés automatiquement depuis la banque de questions.">
            <div className="space-y-2 max-h-52 overflow-auto">
              {openQuizzes.length === 0 && <div className="text-sm text-ink/50">Aucun quiz ouvert.</div>}
              {openQuizzes.map((q) => {
                const sl = secLeft(q);
                return (
                  <div key={q.id} className="border border-lavsoft rounded-xl p-3">
                    <div className="flex items-start gap-2">
                      <span className="text-sm text-ink flex-1">{q.question}</span>
                      {sl != null && <span className="text-[11px] font-mono font-bold px-2 py-0.5 rounded-full bg-lavsoft text-accent shrink-0">⏳ {sl}s</span>}
                    </div>
                    <div className="text-xs text-green-600 font-semibold mt-1">Lot {euro(q.prize)} · réponse : <span className="text-ink/60">{q.answer}</span></div>
                  </div>
                );
              })}
            </div>
          </Card>

          <Card title="❓ Lancer un quiz maison">
            <div className="space-y-2">
              <input className={inp} placeholder="Question" value={qQ} onChange={(e) => setQQ(e.target.value)} />
              <div className="flex gap-2">
                <input className={inp} placeholder="Réponse" value={qA} onChange={(e) => setQA(e.target.value)} />
                <input className={inp} type="number" placeholder="Lot €" value={qP} onChange={(e) => setQP(e.target.value)} />
              </div>
              <button onClick={() => act(() => createQuiz(qQ, qA, +qP), "Quiz lancé")} disabled={!qQ || !qA}
                className="w-full bg-accent text-white font-semibold py-2 rounded-lg hover:bg-ink disabled:opacity-40">Lancer le quiz</button>
            </div>
          </Card>

          <Card title="🕵️ Vendre de l'info (insider)" sub="Les attaquants paient pour une recon facilitée sur une cible.">
            <div className="space-y-2">
              <div className="flex gap-2">
                <input className={inp} placeholder="Client ciblé (ex: bob)" value={iT} onChange={(e) => setIT(e.target.value)} />
                <input className={inp} type="number" placeholder="Prix €" value={iP} onChange={(e) => setIP(e.target.value)} />
              </div>
              <button onClick={() => act(() => createIntelOffer(iT, +iP), "Info mise en vente")} disabled={!iT}
                className="w-full bg-red-600 text-white font-semibold py-2 rounded-lg hover:bg-red-700 disabled:opacity-40">Vendre l'info</button>
            </div>
            <div className="mt-3 space-y-1 max-h-32 overflow-auto">
              {offers.map((o) => (
                <div key={o.id} className="text-sm border-b border-lavsoft py-1 flex items-center gap-2">
                  <span>cible <b>{o.target}</b></span>
                  <span className="ml-auto text-ink/60">{euro(o.price)}</span>
                  {o.sold ? <span className="text-[10px] bg-ink/10 text-ink/50 px-2 py-0.5 rounded-full">vendue</span> : <span className="text-[10px] bg-green-100 text-green-700 px-2 py-0.5 rounded-full">en vente</span>}
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
