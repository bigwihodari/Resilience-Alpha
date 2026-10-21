import { useEffect, useMemo, useRef, useState } from "react";
import { casinoDice, casinoRoulette, bjDeal, bjHit, bjStand } from "../api.js";
import "./casino.css";

const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} €`;
const MAX_BET = 500;

/* ====================================================================
   Sélecteur de mise partagé
   ==================================================================== */
function BetSelector({ bet, setBet, disabled }) {
  const chips = [10, 50, 100, 250, 500];
  const clamp = (v) => Math.max(1, Math.min(MAX_BET, Math.round(v)));
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-sm font-semibold text-ink/70">Mise</span>
      <div className="flex gap-1.5 flex-wrap">
        {chips.map((c) => (
          <button
            key={c}
            disabled={disabled}
            onClick={() => setBet(c)}
            className={`chip-btn text-xs font-bold px-3 py-1.5 rounded-full border disabled:opacity-40 ${
              bet === c
                ? "bg-accent text-white border-accent shadow"
                : "bg-white text-accent border-lav hover:bg-lavsoft"
            }`}
          >
            {c} €
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1 ml-auto">
        <input
          type="number"
          min="1"
          max={MAX_BET}
          value={bet}
          disabled={disabled}
          onChange={(e) => setBet(clamp(parseFloat(e.target.value) || 0))}
          className="w-24 border border-lav rounded-lg px-3 py-1.5 text-sm font-semibold disabled:opacity-40"
        />
        <span className="text-xs text-ink/50">/ {MAX_BET} € max</span>
      </div>
    </div>
  );
}

/* ====================================================================
   Bannière de résultat (gagné / perdu)
   ==================================================================== */
function ResultBanner({ res }) {
  if (!res) return null;
  const win = res.win;
  return (
    <div
      className={`casino-result relative overflow-hidden mt-3 rounded-xl px-4 py-2.5 text-center font-extrabold ${
        win ? "bg-green-500/15 text-green-300" : "bg-red-500/15 text-red-300"
      }`}
    >
      {win && <span className="casino-win-glow absolute inset-0" aria-hidden="true" />}
      <span className="relative z-10">
        {win ? `✨ Gagné +${euro(res.payout)} !` : `Perdu −${euro(res.lost)}`}
      </span>
    </div>
  );
}

/* ====================================================================
   1) DÉS — cube 3D qui roule et s'arrête sur la face du serveur
   ==================================================================== */
const PIPS = {
  1: [4],
  2: [0, 8],
  3: [0, 4, 8],
  4: [0, 2, 6, 8],
  5: [0, 2, 4, 6, 8],
  6: [0, 2, 3, 5, 6, 8],
};
// orientation finale du cube pour présenter la valeur v face caméra : [rotateX, rotateY]
const FACE_ORIENT = { 1: [0, 0], 6: [0, -180], 3: [0, -90], 4: [0, 90], 2: [-90, 0], 5: [90, 0] };

function DieFace({ value, cls }) {
  const on = new Set(PIPS[value]);
  return (
    <div className={`die-face ${cls}`}>
      {Array.from({ length: 9 }, (_, i) => (
        <div key={i} className="die-pip-cell">
          {on.has(i) && <span className="die-pip" />}
        </div>
      ))}
    </div>
  );
}

function DiceGame({ bet, onBalance, onError }) {
  const [choice, setChoice] = useState("high");
  const [rolling, setRolling] = useState(false);
  const [res, setRes] = useState(null);
  const [transform, setTransform] = useState("rotateX(-20deg) rotateY(-20deg)");
  const turns = useRef({ x: 0, y: 0 });
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const bets = [
    { k: "high", label: "Haut 4-6", mult: "×2" },
    { k: "low", label: "Bas 1-3", mult: "×2" },
  ];

  async function roll() {
    if (rolling) return;
    setRes(null);
    setRolling(true);
    let r;
    try {
      r = await casinoDice(bet, choice);
    } catch (e) {
      setRolling(false);
      onError(e.message);
      return;
    }
    // accumule des tours pour un roulement crédible, puis se cale sur r.roll
    turns.current.x += 4;
    turns.current.y += 5;
    const [rx, ry] = FACE_ORIENT[r.roll] || [0, 0];
    setTransform(`rotateX(${turns.current.x * 360 + rx}deg) rotateY(${turns.current.y * 360 + ry}deg)`);
    timer.current = setTimeout(() => {
      setRes({ win: r.win, payout: r.payout, lost: bet, roll: r.roll });
      setRolling(false);
      onBalance && onBalance();
    }, 1400);
  }

  const numChoice = /^[1-6]$/.test(choice);

  return (
    <div className="casino-felt rounded-2xl p-4 text-white flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">🎲</span>
        <h3 className="font-extrabold">Dés</h3>
      </div>

      {/* scène du dé */}
      <div className="flex flex-col items-center justify-center py-3 min-h-[150px]">
        <div className="dice-stage">
          <div className="dice-cube" style={{ transform }}>
            <DieFace value={1} cls="df-1" />
            <DieFace value={2} cls="df-2" />
            <DieFace value={3} cls="df-3" />
            <DieFace value={4} cls="df-4" />
            <DieFace value={5} cls="df-5" />
            <DieFace value={6} cls="df-6" />
          </div>
        </div>
        <div className="dice-shadow mt-4" style={{ opacity: rolling ? 0.35 : 0.6 }} />
      </div>

      {/* choix du pari */}
      <div className="flex gap-2 mb-2">
        {bets.map((x) => (
          <button
            key={x.k}
            disabled={rolling}
            onClick={() => setChoice(x.k)}
            className={`flex-1 rounded-lg py-2 text-sm font-bold transition disabled:opacity-50 ${
              choice === x.k ? "bg-accent text-white ring-2 ring-white/60" : "bg-white/10 text-white hover:bg-white/20"
            }`}
          >
            {x.label}
            <span className="block text-[11px] font-semibold opacity-80">gagne {x.mult}</span>
          </button>
        ))}
      </div>
      <div className="grid grid-cols-6 gap-1 mb-3">
        {[1, 2, 3, 4, 5, 6].map((n) => (
          <button
            key={n}
            disabled={rolling}
            onClick={() => setChoice(String(n))}
            title="Numéro exact — gagne ×6"
            className={`rounded-lg py-1.5 text-sm font-bold transition disabled:opacity-50 ${
              choice === String(n) ? "bg-amber-400 text-ink ring-2 ring-white/70" : "bg-white/10 text-white hover:bg-white/20"
            }`}
          >
            {n}
          </button>
        ))}
      </div>
      {numChoice && <div className="text-[11px] text-white/60 -mt-2 mb-2 text-center">Numéro {choice} exact — gagne ×6</div>}

      <button
        onClick={roll}
        disabled={rolling}
        className="mt-auto w-full rounded-xl bg-amber-400 text-ink font-extrabold py-3 text-lg hover:bg-amber-300 disabled:opacity-60 disabled:cursor-wait transition"
      >
        {rolling ? "🎲 Le dé roule…" : "LANCER LE DÉ"}
      </button>

      <ResultBanner res={res} />
    </div>
  );
}

/* ====================================================================
   2) ROULETTE — roue SVG européenne + bille, décélération réaliste
   ==================================================================== */
const WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26];
const RED = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);
const STEP = 360 / WHEEL.length;

function RouletteWheel({ wheelRot, ballRot }) {
  // construit les 37 secteurs (anneau) une seule fois
  const sectors = useMemo(() => {
    const cx = 150, cy = 150, rOut = 148, rIn = 92, rLabel = 122;
    const pt = (ang, r) => {
      const a = ((ang - 90) * Math.PI) / 180; // 0° = haut
      return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
    };
    return WHEEL.map((num, i) => {
      const a0 = i * STEP - STEP / 2;
      const a1 = i * STEP + STEP / 2;
      const [x0o, y0o] = pt(a0, rOut);
      const [x1o, y1o] = pt(a1, rOut);
      const [x0i, y0i] = pt(a0, rIn);
      const [x1i, y1i] = pt(a1, rIn);
      const d = `M ${x0o} ${y0o} A ${rOut} ${rOut} 0 0 1 ${x1o} ${y1o} L ${x1i} ${y1i} A ${rIn} ${rIn} 0 0 0 ${x0i} ${y0i} Z`;
      const fill = num === 0 ? "#1E8E6A" : RED.has(num) ? "#C1292E" : "#22203f";
      const [lx, ly] = pt(i * STEP, rLabel);
      return { num, d, fill, lx, ly, rot: i * STEP };
    });
  }, []);

  return (
    <div className="roulette-wrap">
      <div className="roulette-pointer" />
      <svg className="roulette-wheel" viewBox="0 0 300 300" style={{ transform: `rotate(${wheelRot}deg)` }}>
        <circle cx="150" cy="150" r="149" fill="#120e26" />
        {sectors.map((s, i) => (
          <g key={i}>
            <path d={s.d} fill={s.fill} stroke="#0d0a1f" strokeWidth="0.8" />
            <text
              x={s.lx}
              y={s.ly}
              fill="#fff"
              fontSize="9"
              fontWeight="700"
              textAnchor="middle"
              dominantBaseline="central"
              transform={`rotate(${s.rot} ${s.lx} ${s.ly})`}
            >
              {s.num}
            </text>
          </g>
        ))}
        <circle cx="150" cy="150" r="92" fill="none" stroke="#E7B53C" strokeWidth="1.5" opacity="0.5" />
      </svg>
      <svg className="roulette-ball-layer" viewBox="0 0 300 300" style={{ transform: `rotate(${ballRot}deg)` }}>
        <circle className="roulette-ball" cx="150" cy="18" r="7" />
      </svg>
      <div className="roulette-hub" />
    </div>
  );
}

function RouletteGame({ bet, onBalance, onError }) {
  const [choice, setChoice] = useState("red");
  const [spinning, setSpinning] = useState(false);
  const [res, setRes] = useState(null);
  const [wheelRot, setWheelRot] = useState(0);
  const [ballRot, setBallRot] = useState(0);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const bets = [
    { k: "red", label: "Rouge ×2", cls: "bg-[#C1292E] text-white" },
    { k: "black", label: "Noir ×2", cls: "bg-ink text-white" },
    { k: "green", label: "Vert ×36", cls: "bg-[#1E8E6A] text-white" },
    { k: "even", label: "Pair ×2", cls: "bg-white/10 text-white" },
    { k: "odd", label: "Impair ×2", cls: "bg-white/10 text-white" },
  ];

  async function spin() {
    if (spinning) return;
    setRes(null);
    setSpinning(true);
    let r;
    try {
      r = await casinoRoulette(bet, choice);
    } catch (e) {
      setSpinning(false);
      onError(e.message);
      return;
    }
    const idx = Math.max(0, WHEEL.indexOf(r.number));
    const targetMod = (360 - idx * STEP) % 360; // amène le secteur gagnant en haut
    const curMod = ((wheelRot % 360) + 360) % 360;
    let delta = targetMod - curMod;
    if (delta < 0) delta += 360;
    setWheelRot((v) => v + 360 * 5 + delta); // 5 tours + alignement
    setBallRot((v) => v - 360 * 8); // bille en sens inverse, se cale en haut
    timer.current = setTimeout(() => {
      setRes({ win: r.win, payout: r.payout, lost: bet, number: r.number, color: r.color });
      setSpinning(false);
      onBalance && onBalance();
    }, 4400);
  }

  const colorText = (c) => (c === "rouge" ? "text-red-300" : c === "vert" ? "text-green-300" : "text-white");

  return (
    <div className="casino-felt rounded-2xl p-4 text-white flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">🎡</span>
        <h3 className="font-extrabold">Roulette</h3>
      </div>

      <RouletteWheel wheelRot={wheelRot} ballRot={ballRot} />

      <div className="text-center mt-2 mb-3 min-h-[1.5rem]">
        {res ? (
          <span className="font-extrabold">
            Sortie : <span className={colorText(res.color)}>{res.number} {res.color}</span>
          </span>
        ) : (
          <span className="text-white/50 text-sm">{spinning ? "La bille tourne…" : "Place ta mise puis lance"}</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3">
        {bets.map((x) => (
          <button
            key={x.k}
            disabled={spinning}
            onClick={() => setChoice(x.k)}
            className={`rounded-lg py-2 text-sm font-bold transition disabled:opacity-50 ${x.cls} ${
              choice === x.k ? "ring-2 ring-amber-300" : "opacity-85 hover:opacity-100"
            }`}
          >
            {x.label} <span className="text-[11px] font-semibold opacity-80">×2</span>
          </button>
        ))}
      </div>

      <button
        onClick={spin}
        disabled={spinning}
        className="mt-auto w-full rounded-xl bg-amber-400 text-ink font-extrabold py-3 text-lg hover:bg-amber-300 disabled:opacity-60 disabled:cursor-wait transition"
      >
        {spinning ? "🎡 Rien ne va plus…" : "LANCER LA BILLE"}
      </button>

      <ResultBanner res={res} />
    </div>
  );
}

/* ====================================================================
   3) BLACKJACK — distribution animée, flip de la carte cachée
   ==================================================================== */
const RED_SUITS = new Set(["♥", "♦"]);
function parseCard(str) {
  const s = String(str);
  const suit = s.slice(-1);
  const rank = s.slice(0, -1);
  return { rank, suit, red: RED_SUITS.has(suit) };
}

function PlayingCard({ card, deal, delay }) {
  const c = parseCard(card);
  return (
    <div className={`bj-card ${deal ? "dealing" : ""}`} style={deal ? { animationDelay: `${delay}s` } : undefined}>
      <span className={`bj-rank-tl ${c.red ? "bj-red" : "bj-blk"}`}>{c.rank}{c.suit}</span>
      <span className={`bj-suit-c ${c.red ? "bj-red" : "bj-blk"}`}>{c.suit}</span>
      <span className={`bj-rank-br ${c.red ? "bj-red" : "bj-blk"}`}>{c.rank}{c.suit}</span>
    </div>
  );
}

// carte à face cachée (croupier) qui se retourne quand révélée
function FlipCard({ card, revealed, deal, delay }) {
  const c = parseCard(card);
  return (
    <div className={`bj-flip ${revealed ? "revealed" : ""} ${deal ? "dealing" : ""}`} style={deal ? { animationDelay: `${delay}s` } : undefined}>
      <div className="bj-flip-inner">
        <div className="bj-face bj-back" />
        <div className="bj-face bj-front bj-card" style={{ boxShadow: "none" }}>
          <span className={`bj-rank-tl ${c.red ? "bj-red" : "bj-blk"}`}>{c.rank}{c.suit}</span>
          <span className={`bj-suit-c ${c.red ? "bj-red" : "bj-blk"}`}>{c.suit}</span>
          <span className={`bj-rank-br ${c.red ? "bj-red" : "bj-blk"}`}>{c.rank}{c.suit}</span>
        </div>
      </div>
    </div>
  );
}

function BlackjackGame({ bet, onBalance, onError }) {
  const [bj, setBj] = useState(null);
  const [busy, setBusy] = useState(false);
  const [roundId, setRoundId] = useState(0);
  // suivi des cartes déjà affichées pour n'animer que les nouvelles
  const shown = useRef({ round: -1, p: 0, d: 0 });

  const over = !bj || bj.over;
  const playing = bj && !bj.over;

  // calcule, pour chaque main, à partir de quel index les cartes sont "neuves"
  const base = shown.current.round === roundId ? shown.current : { p: 0, d: 0 };

  useEffect(() => {
    if (bj) shown.current = { round: roundId, p: (bj.player || []).length, d: (bj.dealer || []).length };
  }, [bj, roundId]);

  async function run(fn, fresh) {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fn();
      if (fresh) setRoundId((x) => x + 1);
      setBj(r);
      if (r.over) onBalance && onBalance();
      // laisse jouer l'animation de distribution avant de réactiver
      setTimeout(() => setBusy(false), fresh ? 700 : 520);
    } catch (e) {
      setBusy(false);
      onError(e.message);
    }
  }

  const deal = () => run(() => bjDeal(bet), true);
  const hit = () => run(() => bjHit(), false);
  const stand = () => run(() => bjStand(), false);

  const player = bj?.player || [];
  const dealer = bj?.dealer || [];
  const basePForFresh = shown.current.round === roundId ? base.p : 0;
  const baseDForFresh = shown.current.round === roundId ? base.d : 0;

  const result = bj?.over
    ? { win: (bj.payout || 0) > 0, payout: bj.payout, lost: bet, text: bj.result }
    : null;

  return (
    <div className="casino-felt bj-table rounded-2xl p-4 text-white flex flex-col">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">🃏</span>
        <h3 className="font-extrabold">Blackjack</h3>
      </div>

      <div className="flex-1 min-h-[220px] flex flex-col justify-between gap-3">
        {/* Croupier */}
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-white/60 mb-1">
            Croupier
            <span className="ml-auto bg-white/10 rounded-full px-2 py-0.5 text-white font-bold">
              {bj ? (playing ? "?" : bj.dealer_total) : "—"}
            </span>
          </div>
          <div className="flex gap-1.5 min-h-[84px]">
            {dealer.map((card, i) => {
              const isHole = i === 1; // 2ᵉ carte cachée tant qu'on joue
              const isNew = i >= baseDForFresh;
              const delay = Math.max(0, i - baseDForFresh) * 0.13 + (i === 0 ? 0.13 : 0.26);
              return isHole ? (
                <FlipCard key={`${roundId}-d-${i}`} card={card} revealed={over} deal={isNew} delay={delay} />
              ) : (
                <PlayingCard key={`${roundId}-d-${i}`} card={card} deal={isNew} delay={delay} />
              );
            })}
            {!bj && <div className="bj-card opacity-20" />}
          </div>
        </div>

        {/* Joueur */}
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold text-white/60 mb-1">
            Toi
            <span
              className={`ml-auto rounded-full px-2 py-0.5 font-bold ${
                bj && bj.player_total > 21 ? "bg-red-500/30 text-red-200" : "bg-white/10 text-white"
              }`}
            >
              {bj ? bj.player_total : "—"}
            </span>
          </div>
          <div className="flex gap-1.5 min-h-[84px]">
            {player.map((card, i) => {
              const isNew = i >= basePForFresh;
              const delay = Math.max(0, i - basePForFresh) * 0.13;
              return <PlayingCard key={`${roundId}-p-${i}`} card={card} deal={isNew} delay={delay} />;
            })}
            {!bj && <div className="bj-card opacity-20" />}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="mt-3">
        {over ? (
          <button
            onClick={deal}
            disabled={busy}
            className="w-full rounded-xl bg-amber-400 text-ink font-extrabold py-3 text-lg hover:bg-amber-300 disabled:opacity-60 disabled:cursor-wait transition"
          >
            {busy ? "Distribution…" : bj ? "REJOUER" : "DISTRIBUER"}
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={hit}
              disabled={busy}
              className="flex-1 rounded-xl bg-green-500 text-white font-extrabold py-3 hover:bg-green-400 disabled:opacity-60 disabled:cursor-wait transition"
            >
              Tirer
            </button>
            <button
              onClick={stand}
              disabled={busy}
              className="flex-1 rounded-xl bg-white/15 text-white font-extrabold py-3 hover:bg-white/25 disabled:opacity-60 disabled:cursor-wait transition"
            >
              Rester
            </button>
          </div>
        )}
      </div>

      {result && (
        <div
          className={`casino-result relative overflow-hidden mt-3 rounded-xl px-4 py-2.5 text-center font-extrabold ${
            result.win ? "bg-green-500/15 text-green-300" : "bg-red-500/15 text-red-300"
          }`}
        >
          {result.win && <span className="casino-win-glow absolute inset-0" aria-hidden="true" />}
          <span className="relative z-10">
            {result.text}
            {result.win ? ` — +${euro(result.payout)}` : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/* ====================================================================
   Page Casino
   ==================================================================== */
export default function Casino({ onBalance }) {
  const [bet, setBet] = useState(50);
  const [err, setErr] = useState(null);
  const onError = (m) => {
    setErr(m);
    setTimeout(() => setErr(null), 4000);
  };

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl shadow p-4 flex flex-col gap-3 animate-in">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-2xl">🎰</span>
          <h2 className="text-lg font-extrabold text-ink">Casino</h2>
          <span className="text-sm text-ink/50">Choisis ta mise, puis lance le jeu que tu veux.</span>
        </div>
        <BetSelector bet={bet} setBet={setBet} disabled={false} />
        {err && <div className="text-sm font-semibold text-red-600 bg-red-50 rounded-lg px-3 py-2">⚠️ {err}</div>}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <DiceGame bet={bet} onBalance={onBalance} onError={onError} />
        <RouletteGame bet={bet} onBalance={onBalance} onError={onError} />
        <BlackjackGame bet={bet} onBalance={onBalance} onError={onError} />
      </div>

      <p className="text-xs text-ink/50">
        Mise plafonnée à {MAX_BET} €. Les gains et pertes vont sur ton compte courant — de quoi grimper (ou chuter) au classement.
        Le serveur fait foi : l'animation s'arrête toujours sur le résultat officiel.
      </p>
    </div>
  );
}
