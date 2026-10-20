import { useState } from "react";
import { casinoDice, casinoRoulette, bjDeal, bjHit, bjStand } from "../api.js";

const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} €`;

export default function Casino({ onBalance }) {
  const [bet, setBet] = useState("50");
  const [msg, setMsg] = useState(null);
  const [dice, setDice] = useState(null);
  const [roul, setRoul] = useState(null);
  const [bj, setBj] = useState(null);
  const b = () => Math.max(1, parseFloat(bet) || 0);
  const flash = (t, ok = true) => { setMsg({ t, ok }); setTimeout(() => setMsg(null), 3000); };
  const after = () => { if (onBalance) onBalance(); };

  async function playDice(choice) {
    try { const r = await casinoDice(b(), choice); setDice(r); flash(r.win ? `🎲 ${r.roll} — gagné ${euro(r.payout)} !` : `🎲 ${r.roll} — perdu`, r.win); after(); }
    catch (e) { flash(e.message, false); }
  }
  async function playRoul(choice) {
    try { const r = await casinoRoulette(b(), choice); setRoul(r); flash(r.win ? `🎡 ${r.number} ${r.color} — gagné ${euro(r.payout)} !` : `🎡 ${r.number} ${r.color} — perdu`, r.win); after(); }
    catch (e) { flash(e.message, false); }
  }
  async function bjStart() { try { setBj(await bjDeal(b())); after(); } catch (e) { flash(e.message, false); } }
  async function bjDo(fn) { try { const r = await fn(); setBj(r); if (r.over) { flash(`🃏 ${r.result}${r.payout ? " — " + euro(r.payout) : ""}`, r.payout > 0); after(); } } catch (e) { flash(e.message, false); } }

  const Card = ({ title, children }) => (
    <div className="bg-white rounded-2xl shadow p-4"><div className="font-bold text-ink mb-2">{title}</div>{children}</div>
  );
  const chip = "text-sm font-semibold px-3 py-1.5 rounded-lg transition";

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow p-4 flex items-center gap-3 flex-wrap">
        <span className="font-bold text-ink">🎰 Casino</span>
        <label className="text-sm text-ink/60 ml-auto">Mise (€)</label>
        <input type="number" min="1" value={bet} onChange={(e) => setBet(e.target.value)} className="w-28 border border-lav rounded-lg px-3 py-1.5" />
        {msg && <span className={`w-full text-sm font-semibold ${msg.ok ? "text-green-700" : "text-red-600"}`}>{msg.t}</span>}
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        {/* Dés */}
        <Card title="🎲 Dés">
          <div className="flex gap-2 flex-wrap">
            <button onClick={() => playDice("high")} className={`${chip} bg-accent text-white hover:bg-ink`}>Haut (4-6) ×2</button>
            <button onClick={() => playDice("low")} className={`${chip} bg-accent text-white hover:bg-ink`}>Bas (1-3) ×2</button>
          </div>
          <div className="flex gap-1 mt-2">
            {[1, 2, 3, 4, 5, 6].map((n) => <button key={n} onClick={() => playDice(String(n))} className={`${chip} bg-lavsoft text-accent hover:bg-lav/40 w-9`} title="numéro exact ×6">{n}</button>)}
          </div>
          {dice && <div className="mt-3 text-center text-4xl font-black text-ink">{dice.roll}</div>}
        </Card>

        {/* Roulette */}
        <Card title="🎡 Roulette">
          <div className="flex gap-2 flex-wrap">
            <button onClick={() => playRoul("red")} className={`${chip} bg-red-600 text-white hover:bg-red-700`}>Rouge ×2</button>
            <button onClick={() => playRoul("black")} className={`${chip} bg-ink text-white hover:bg-black`}>Noir ×2</button>
            <button onClick={() => playRoul("even")} className={`${chip} bg-lavsoft text-accent`}>Pair ×2</button>
            <button onClick={() => playRoul("odd")} className={`${chip} bg-lavsoft text-accent`}>Impair ×2</button>
          </div>
          {roul && <div className={`mt-3 text-center text-4xl font-black ${roul.color === "rouge" ? "text-red-600" : roul.color === "vert" ? "text-green-600" : "text-ink"}`}>{roul.number} <span className="text-sm align-middle">{roul.color}</span></div>}
        </Card>

        {/* Blackjack */}
        <Card title="🃏 Blackjack">
          {!bj || bj.over ? (
            <button onClick={bjStart} className={`${chip} bg-accent text-white hover:bg-ink w-full`}>Distribuer</button>
          ) : (
            <div className="flex gap-2">
              <button onClick={() => bjDo(bjHit)} className={`${chip} bg-green-600 text-white hover:bg-green-700 flex-1`}>Tirer</button>
              <button onClick={() => bjDo(bjStand)} className={`${chip} bg-ink text-white hover:bg-accent flex-1`}>Rester</button>
            </div>
          )}
          {bj && (
            <div className="mt-3 text-sm space-y-1">
              <div>Toi : <b>{(bj.player || []).join(" + ")}</b> = <b className={bj.player_total > 21 ? "text-red-600" : "text-ink"}>{bj.player_total}</b></div>
              <div>Croupier : <b>{(bj.dealer || []).join(" + ")}</b> = <b>{bj.dealer_total}</b></div>
              {bj.over && <div className={`font-bold ${bj.payout > 0 ? "text-green-700" : "text-red-600"}`}>{bj.result}{bj.payout ? ` — +${euro(bj.payout)}` : ""}</div>}
            </div>
          )}
        </Card>
      </div>
      <p className="text-xs text-ink/50">Mise plafonnée. Les gains/pertes vont sur ton compte courant — à utiliser pour grimper (ou chuter) au classement !</p>
    </div>
  );
}
