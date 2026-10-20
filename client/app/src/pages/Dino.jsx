import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { dinoClaim } from "../api.js";

export default function Dino() {
  const nav = useNavigate();
  const canvasRef = useRef(null);
  const [state, setState] = useState("idle"); // idle | run | over
  const [coins, setCoins] = useState(0);
  const [mult, setMult] = useState(1);
  const [result, setResult] = useState(null);
  const g = useRef({});

  function start() {
    const c = canvasRef.current;
    g.current = {
      t: 0, speed: 4, dino: { y: 0, vy: 0 }, ground: c.height - 30,
      obstacles: [], coins: [], bonuses: [], coinCount: 0, mult: 1, alive: true,
    };
    setCoins(0); setMult(1); setResult(null); setState("run");
  }

  function jump() {
    const s = g.current;
    if (state !== "run" || !s.dino) return;
    if (s.dino.y === 0) s.dino.vy = -11;
  }

  async function gameOver() {
    const s = g.current; s.alive = false;
    setState("over");
    try {
      const r = await dinoClaim(s.coinCount, s.mult);
      setResult(r);
    } catch (e) { setResult({ error: e.message }); }
  }

  useEffect(() => {
    const onKey = (e) => { if (e.code === "Space") { e.preventDefault(); if (state === "run") jump(); else start(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [state]);

  useEffect(() => {
    if (state !== "run") return;
    const c = canvasRef.current, ctx = c.getContext("2d");
    let raf;
    const loop = () => {
      const s = g.current;
      if (!s.alive) return;
      s.t += 1;
      s.speed = 4 + s.t / 900;
      // dino physics
      s.dino.vy += 0.6; s.dino.y = Math.min(0, s.dino.y + s.dino.vy);
      if (s.dino.y >= 0) { s.dino.y = 0; s.dino.vy = 0; }
      // spawns
      if (s.t % Math.max(55, 110 - Math.floor(s.t / 60)) === 0) s.obstacles.push({ x: c.width, w: 16 + Math.random() * 14, h: 24 + Math.random() * 22 });
      if (s.t % 70 === 0) s.coins.push({ x: c.width, y: s.ground - 40 - Math.random() * 70, got: false });
      if (s.t % 650 === 0) s.bonuses.push({ x: c.width, y: s.ground - 90, v: [5, 10, 100][Math.floor(Math.random() * 3)], got: false });
      const dinoX = 50, dinoW = 22, dinoH = 26;
      const dinoTop = s.ground - dinoH + s.dino.y;
      // move + collide
      s.obstacles.forEach((o) => { o.x -= s.speed; });
      s.obstacles = s.obstacles.filter((o) => o.x + o.w > 0);
      for (const o of s.obstacles) {
        if (dinoX < o.x + o.w && dinoX + dinoW > o.x && dinoTop + dinoH > s.ground - o.h) { gameOver(); return; }
      }
      s.coins.forEach((cn) => { cn.x -= s.speed; });
      s.coins = s.coins.filter((cn) => cn.x + 12 > 0);
      for (const cn of s.coins) {
        if (!cn.got && dinoX < cn.x + 10 && dinoX + dinoW > cn.x && dinoTop < cn.y + 10 && dinoTop + dinoH > cn.y) {
          cn.got = true; s.coinCount += s.mult; setCoins(s.coinCount);
        }
      }
      s.bonuses.forEach((b) => { b.x -= s.speed; });
      s.bonuses = s.bonuses.filter((b) => b.x + 16 > 0);
      for (const b of s.bonuses) {
        if (!b.got && dinoX < b.x + 16 && dinoX + dinoW > b.x && dinoTop < b.y + 16 && dinoTop + dinoH > b.y) {
          b.got = true; s.mult = Math.max(s.mult, b.v); setMult(s.mult);
        }
      }
      // draw
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.fillStyle = "#EEF0F8"; ctx.fillRect(0, 0, c.width, c.height);
      ctx.strokeStyle = "#A1A6D4"; ctx.beginPath(); ctx.moveTo(0, s.ground); ctx.lineTo(c.width, s.ground); ctx.stroke();
      ctx.fillStyle = "#4B3FA6"; ctx.fillRect(dinoX, dinoTop, dinoW, dinoH);
      ctx.fillStyle = "#1E8E6A"; s.obstacles.forEach((o) => ctx.fillRect(o.x, s.ground - o.h, o.w, o.h));
      s.coins.forEach((cn) => { if (!cn.got) { ctx.fillStyle = "#E7B53C"; ctx.beginPath(); ctx.arc(cn.x + 5, cn.y + 5, 6, 0, 7); ctx.fill(); } });
      s.bonuses.forEach((b) => { if (!b.got) { ctx.fillStyle = "#C2413C"; ctx.font = "bold 16px sans-serif"; ctx.fillText("x" + b.v, b.x, b.y + 14); } });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [state]);

  return (
    <div className="max-w-3xl mx-auto p-4">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav("/dashboard")} className="text-sm bg-white px-3 py-1.5 rounded-lg shadow">← Retour</button>
        <h1 className="text-xl font-extrabold text-ink">🦖 Dino — récolte des pièces</h1>
      </div>
      <div className="bg-white rounded-2xl shadow p-4">
        <div className="flex items-center gap-4 mb-2">
          <div className="text-sm">Pièces : <b className="text-amber-600">{coins}</b></div>
          <div className="text-sm">Multiplicateur : <b className="text-red-600">x{mult}</b></div>
          <div className="ml-auto text-xs text-ink/50">Espace / clic = sauter</div>
        </div>
        <canvas ref={canvasRef} width={640} height={200} onClick={() => (state === "run" ? jump() : start())}
          className="w-full rounded-xl border border-lav cursor-pointer" style={{ touchAction: "manipulation" }} />
        <div className="mt-3 text-center">
          {state === "idle" && <button onClick={start} className="bg-accent text-white font-bold px-6 py-2.5 rounded-xl hover:bg-ink">▶ Jouer</button>}
          {state === "over" && (
            <div>
              <div className="font-bold text-ink mb-2">Partie terminée — {coins} pièces (x{mult})</div>
              {result && !result.error && <div className="text-green-700 font-semibold mb-2">+{Number(result.earned ?? result.credited ?? 0).toLocaleString("fr-FR")} € crédités (nouveau solde {Number(result.balance ?? 0).toLocaleString("fr-FR")} €)</div>}
              {result && result.error && <div className="text-red-600 text-sm mb-2">{result.error}</div>}
              <button onClick={start} className="bg-accent text-white font-bold px-6 py-2.5 rounded-xl hover:bg-ink">↻ Rejouer</button>
            </div>
          )}
        </div>
      </div>
      <p className="text-xs text-ink/50 mt-3">Saute les cactus, ramasse les pièces dorées. Les jetons rouges x5/x10/x100 boostent la valeur de tes pièces. À la fin, tes pièces sont converties en argent (plafonné) sur ton compte.</p>
    </div>
  );
}
