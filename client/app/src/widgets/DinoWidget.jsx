import { useEffect, useRef, useState } from "react";
import { dinoClaim } from "../api.js";

// Mini-jeu Dino en pop-up (bouton flottant). Le jeu ne capte le clavier que
// quand la pop-up est ouverte. Difficulté/vitesse montent progressivement ;
// pièces placées dans les trous entre obstacles (toujours attrapables).
export default function DinoWidget({ onEarned }) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState("idle"); // idle | run | over
  const [hud, setHud] = useState({ coins: 0, mult: 1, speed: 0 });
  const [result, setResult] = useState(null);
  const canvasRef = useRef(null);
  const g = useRef(null);
  const rafRef = useRef(0);

  const W = 620, H = 240, GROUND = H - 42;
  const DINO = { x: 62, w: 26, h: 30 };
  const GRAV = 0.9, JUMP = -13.5;

  function reset() {
    g.current = {
      t: 0, speed: 3.4, dy: 0, vy: 0, onGround: true,
      obstacles: [], coins: [], bonuses: [],
      nextObstacleIn: 70, coins_: 0, mult: 1, alive: true, best: g.current?.best || 0,
    };
    setHud({ coins: 0, mult: 1, speed: 3.4 });
    setResult(null);
  }

  function startGame() { reset(); setPhase("run"); }

  function jump() {
    const s = g.current;
    if (!s || !s.alive) return;
    if (s.onGround) { s.vy = JUMP; s.onGround = false; }
  }

  async function over() {
    const s = g.current; if (!s) return;
    s.alive = false; setPhase("over");
    try { const r = await dinoClaim(s.coins_, s.mult); setResult(r); if (onEarned) onEarned(); }
    catch (e) { setResult({ error: e.message }); }
  }

  // clavier : seulement quand la pop-up est ouverte
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.code === "Space" || e.code === "ArrowUp") {
        e.preventDefault();
        if (phase === "run") jump(); else startGame();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, phase]);

  // boucle de jeu
  useEffect(() => {
    if (!open || phase !== "run") { cancelAnimationFrame(rafRef.current); return; }
    const c = canvasRef.current, ctx = c.getContext("2d");
    const spawnObstacle = (s) => {
      const h = 22 + Math.random() * 26;
      s.obstacles.push({ x: W + 10, w: 16 + Math.random() * 12, h });
      // trou jusqu'au prochain obstacle : proportionnel à la vitesse -> toujours franchissable
      s.nextObstacleIn = Math.round((150 + s.speed * 26 + Math.random() * 120));
      // pièces dans le trou, à hauteur attrapable (arc de saut), avant le prochain obstacle
      if (Math.random() < 0.85) {
        const n = 3 + Math.floor(Math.random() * 3);
        const startX = W + 10 + s.nextObstacleIn * 0.45;
        const baseY = GROUND - 30 - Math.random() * 55;
        for (let i = 0; i < n; i++) s.coins.push({ x: startX + i * 26, y: baseY - Math.sin(i / (n - 1) * Math.PI) * 26, got: false });
      }
      // bonus multiplicateur rare
      if (Math.random() < 0.12) {
        s.bonuses.push({ x: W + 10 + s.nextObstacleIn * 0.7, y: GROUND - 95, v: [5, 10, 100][Math.floor(Math.random() * 3)], got: false });
      }
    };
    const step = () => {
      const s = g.current; if (!s || !s.alive) return;
      s.t += 1;
      s.speed = Math.min(9.5, 3.4 + s.t / 520);           // accélération progressive
      // physique dino
      s.vy += GRAV; s.dy += s.vy;
      if (s.dy >= 0) { s.dy = 0; s.vy = 0; s.onGround = true; }
      const dinoTop = GROUND - DINO.h + s.dy;
      // spawn basé sur la distance
      s.nextObstacleIn -= s.speed;
      if (s.nextObstacleIn <= 0) spawnObstacle(s);
      // déplacements
      const move = (arr) => arr.forEach((o) => (o.x -= s.speed));
      move(s.obstacles); move(s.coins); move(s.bonuses);
      s.obstacles = s.obstacles.filter((o) => o.x + o.w > -5);
      s.coins = s.coins.filter((o) => o.x > -15);
      s.bonuses = s.bonuses.filter((o) => o.x > -20);
      // collisions obstacles
      for (const o of s.obstacles) {
        if (DINO.x + DINO.w - 4 > o.x && DINO.x + 4 < o.x + o.w && dinoTop + DINO.h > GROUND - o.h + 3) { over(); return; }
      }
      // pièces
      for (const cn of s.coins) {
        if (!cn.got && Math.abs((DINO.x + DINO.w / 2) - cn.x) < 18 && Math.abs((dinoTop + DINO.h / 2) - cn.y) < 20) {
          cn.got = true; s.coins_ += s.mult; setHud({ coins: s.coins_, mult: s.mult, speed: +s.speed.toFixed(1) });
        }
      }
      // bonus
      for (const b of s.bonuses) {
        if (!b.got && Math.abs((DINO.x + DINO.w / 2) - b.x) < 22 && Math.abs((dinoTop + DINO.h / 2) - b.y) < 24) {
          b.got = true; s.mult = Math.max(s.mult, b.v); setHud({ coins: s.coins_, mult: s.mult, speed: +s.speed.toFixed(1) });
        }
      }
      // rendu
      const sky = ctx.createLinearGradient(0, 0, 0, H); sky.addColorStop(0, "#EEF0F8"); sky.addColorStop(1, "#DDE0F2");
      ctx.fillStyle = sky; ctx.fillRect(0, 0, W, H);
      ctx.strokeStyle = "#A1A6D4"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(0, GROUND); ctx.lineTo(W, GROUND); ctx.stroke();
      // dino
      ctx.fillStyle = "#4B3FA6"; roundRect(ctx, DINO.x, dinoTop, DINO.w, DINO.h, 6); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillRect(DINO.x + DINO.w - 9, dinoTop + 7, 4, 4);
      // obstacles
      ctx.fillStyle = "#1E8E6A"; s.obstacles.forEach((o) => roundRect(ctx, o.x, GROUND - o.h, o.w, o.h, 3) || ctx.fill());
      // coins
      s.coins.forEach((cn) => { if (!cn.got) { ctx.fillStyle = "#E7B53C"; ctx.beginPath(); ctx.arc(cn.x, cn.y, 7, 0, 7); ctx.fill(); ctx.fillStyle = "#fff8e1"; ctx.beginPath(); ctx.arc(cn.x - 2, cn.y - 2, 2.2, 0, 7); ctx.fill(); } });
      // bonus
      s.bonuses.forEach((b) => { if (!b.got) { ctx.fillStyle = "#E5484D"; roundRect(ctx, b.x - 14, b.y - 11, 30, 22, 6); ctx.fill(); ctx.fillStyle = "#fff"; ctx.font = "bold 13px system-ui"; ctx.textAlign = "center"; ctx.fillText("x" + b.v, b.x, b.y + 5); } });
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [open, phase]);

  function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); return true; }

  return (
    <>
      <button onClick={() => { setOpen(true); }} title="Mini-jeu Dino"
        className="fixed z-40 bottom-5 left-5 w-14 h-14 rounded-full bg-accent text-white text-2xl shadow-lg hover:bg-ink transition flex items-center justify-center">🦖</button>

      {open && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={() => { setOpen(false); setPhase("idle"); }}>
          <div className="bg-white rounded-2xl shadow-2xl p-4 w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-2">
              <div className="font-extrabold text-ink text-lg">🦖 Dino — récolte des pièces</div>
              <button onClick={() => { setOpen(false); setPhase("idle"); }} className="ml-auto text-ink/50 hover:text-red-500 text-xl leading-none">×</button>
            </div>
            <div className="flex items-center gap-4 text-sm mb-2">
              <span>Pièces <b className="text-amber-600">{hud.coins}</b></span>
              <span>Multi <b className="text-red-600">x{hud.mult}</b></span>
              <span className="text-ink/50">Vitesse {hud.speed}</span>
              <span className="ml-auto text-xs text-ink/50">Espace / clic = sauter</span>
            </div>
            <canvas ref={canvasRef} width={W} height={H} onClick={() => (phase === "run" ? jump() : startGame())}
              className="w-full rounded-xl border border-lav cursor-pointer select-none" style={{ touchAction: "manipulation" }} />
            <div className="mt-3 text-center min-h-[3rem]">
              {phase === "idle" && <button onClick={startGame} className="bg-accent text-white font-bold px-6 py-2.5 rounded-xl hover:bg-ink">▶ Jouer</button>}
              {phase === "over" && (
                <div>
                  <div className="font-bold text-ink mb-1">Partie terminée — {hud.coins} pièces (x{hud.mult})</div>
                  {result && !result.error && <div className="text-green-700 font-semibold mb-2">+{Number(result.earned ?? result.credited ?? 0).toLocaleString("fr-FR")} € crédités</div>}
                  {result && result.error && <div className="text-red-600 text-sm mb-2">{result.error}</div>}
                  <button onClick={startGame} className="bg-accent text-white font-bold px-6 py-2.5 rounded-xl hover:bg-ink">↻ Rejouer</button>
                </div>
              )}
            </div>
            <p className="text-xs text-ink/50">Saute les cactus (verts), ramasse les pièces (or). Les jetons rouges x5/x10/x100 boostent la valeur. La vitesse augmente avec le temps.</p>
          </div>
        </div>
      )}
    </>
  );
}
