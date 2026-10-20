import { useEffect, useRef, useState } from "react";
import { haCluster, promInstant, scalar, orchStatus } from "../api.js";

function ago(ts) {
  if (!ts) return "jamais";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 2) return "à l'instant";
  if (s < 60) return `il y a ${s}s`;
  return `il y a ${Math.round(s / 60)} min`;
}

// Décrit l'état d'un nœud pour l'affichage (libellé + couleur).
function describe(node, serving) {
  if (!node || !node.reachable) return { label: "Hors ligne", tone: "offline" };
  const isServing = node.name === serving;
  if (node.role_cfg === "primary") {
    return isServing
      ? { label: "Actif — sert le trafic", tone: "active" }
      : { label: "En ligne", tone: "idle" };
  }
  // secours
  if (node.promoted) return { label: "PROMU — a pris le relais", tone: "promoted" };
  return { label: "En réplication (prêt)", tone: "standby" };
}

const TONE = {
  active: { ring: "ring-green-400", bg: "from-green-600 to-emerald-700", badge: "bg-green-100 text-green-700", dot: "bg-green-400" },
  promoted: { ring: "ring-amber-400", bg: "from-amber-600 to-red-600", badge: "bg-amber-100 text-amber-700", dot: "bg-amber-400" },
  standby: { ring: "ring-lav", bg: "from-ink to-accent", badge: "bg-lavsoft text-accent", dot: "bg-accent" },
  idle: { ring: "ring-lav", bg: "from-ink to-accent", badge: "bg-lavsoft text-accent", dot: "bg-lav" },
  offline: { ring: "ring-red-400", bg: "from-gray-500 to-gray-700", badge: "bg-red-100 text-red-700", dot: "bg-red-500" },
};

function Node({ node, serving }) {
  const d = describe(node, serving);
  const t = TONE[d.tone];
  const off = d.tone === "offline";
  return (
    <div className={`flex-1 rounded-2xl p-5 shadow-lg ring-2 ${t.ring} bg-gradient-to-br ${t.bg} text-white transition-all ${off ? "opacity-70" : ""}`}>
      <div className="flex items-center gap-2">
        <span className={`w-3 h-3 rounded-full ${t.dot} ${!off ? "animate-pulse" : ""}`}></span>
        <span className="text-xs uppercase tracking-widest opacity-80">
          {node?.role_cfg === "primary" ? "Serveur principal" : "Serveur de secours"}
        </span>
      </div>
      <div className="text-3xl font-extrabold mt-2">{node?.name || "—"}</div>
      <div className={`inline-block mt-3 text-sm font-bold px-3 py-1 rounded-full ${t.badge}`}>{d.label}</div>
      <div className="mt-4 text-sm space-y-1 opacity-90">
        {node?.role_cfg === "backup" && (
          <div>Dernière synchro : <b>{ago(node?.last_sync)}</b></div>
        )}
        {typeof node?.fails === "number" && node.fails > 0 && (
          <div className="text-amber-200">Échecs consécutifs : <b>{node.fails}</b></div>
        )}
        {off && <div className="text-red-200 font-semibold">Injoignable — le trafic a basculé</div>}
      </div>
    </div>
  );
}

export default function HauteDispo() {
  const [cluster, setCluster] = useState(null);
  const [ia, setIa] = useState({ score: 0, flag: false, trained: false });
  const [rem, setRem] = useState(null);
  const timer = useRef(null);

  async function refresh() {
    const [c, anom, flag, trained, orch] = await Promise.all([
      haCluster(),
      promInstant("anomaly_score"),
      promInstant("anomaly_flag"),
      promInstant("detector_trained"),
      orchStatus(),
    ]);
    if (c) setCluster(c);
    setIa({ score: Math.round(scalar(anom) * 10) / 10, flag: scalar(flag) === 1, trained: scalar(trained) === 1 });
    setRem(orch);
  }

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 1500);
    return () => clearInterval(timer.current);
  }, []);

  const serving = cluster?.serving;
  const servingBackup = cluster?.secours?.name === serving && cluster?.secours?.promoted;

  // Fusion des événements de bascule (principal + secours), les plus récents d'abord.
  const events = [
    ...((cluster?.principal?.events) || []),
    ...((cluster?.secours?.events) || []),
  ].sort((a, b) => (a.t < b.t ? 1 : -1)).slice(0, 18);

  const kindColor = { success: "text-green-700", alert: "text-red-700", error: "text-red-700", action: "text-accent", info: "text-ink/60" };

  return (
    <div className="max-w-5xl mx-auto p-5">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="text-2xl font-extrabold text-ink">Haute disponibilité</h1>
        <span className="ml-auto inline-flex items-center gap-2 text-sm bg-white px-3 py-1.5 rounded-full shadow">
          <span className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse"></span> Suivi live
        </span>
      </div>

      {/* Bannière : qui sert le trafic */}
      <div className={`rounded-2xl p-4 mb-6 text-center font-bold shadow ${servingBackup ? "bg-amber-50 text-amber-800 border border-amber-300" : "bg-green-50 text-green-800 border border-green-200"}`}>
        {serving ? (
          servingBackup
            ? <>⚠ BASCULE EN COURS — le trafic est servi par le SECOURS ({serving})</>
            : <>✓ Fonctionnement nominal — le trafic est servi par le PRINCIPAL ({serving})</>
        ) : <>Recherche de l'état du cluster…</>}
      </div>

      {/* Les deux nœuds + flux au milieu */}
      <div className="flex flex-col md:flex-row items-stretch gap-4 mb-6">
        <Node node={cluster?.principal} serving={serving} />
        <div className="flex md:flex-col items-center justify-center px-2">
          <div className={`text-3xl ${servingBackup ? "text-amber-500" : "text-green-500"}`}>
            {servingBackup ? "⇄" : "→"}
          </div>
          <div className="text-[11px] text-ink/50 text-center mt-1 w-20">trafic<br />clients</div>
        </div>
        <Node node={cluster?.secours} serving={serving} />
      </div>

      {/* Calcul du système IA (détection + décision) */}
      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Décision du système IA</h2>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className={`rounded-2xl shadow p-5 text-center ${ia.flag ? "bg-red-50 border border-red-300" : "bg-white"}`}>
          <div className="text-xs text-ink/50 font-semibold uppercase tracking-wide">Score d'anomalie (Isolation Forest)</div>
          <div className={`text-5xl font-extrabold mt-2 ${ia.flag ? "text-red-600" : "text-green-600"}`}>
            {ia.trained ? ia.score : "—"}
          </div>
          <div className="mt-2 text-sm">
            {!ia.trained ? <span className="text-ink/50">🧠 apprentissage…</span>
              : ia.flag ? <span className="font-bold text-red-700 bg-red-100 px-3 py-1 rounded-full">⚠ ANOMALIE</span>
              : <span className="font-bold text-green-700 bg-green-100 px-3 py-1 rounded-full">✓ Normal</span>}
          </div>
        </div>
        <div className="lg:col-span-2 bg-white rounded-2xl shadow p-5">
          <div className="font-bold text-ink mb-2">Raisonnement</div>
          <ol className="text-sm text-ink/80 space-y-1.5 list-decimal list-inside">
            <li>Le détecteur ML calcule un score d'anomalie sur le trafic en continu.</li>
            <li className={ia.flag ? "text-red-700 font-semibold" : ""}>
              {ia.flag ? "Anomalie confirmée → le principal est considéré menacé." : "Trafic nominal → le principal sert le trafic."}
            </li>
            <li className={servingBackup ? "text-amber-700 font-semibold" : ""}>
              {servingBackup
                ? "Principal injoignable → promotion automatique du secours (exactly-once, aucune transaction perdue)."
                : "Si le principal tombe (3 échecs de réplication), le secours est promu automatiquement."}
            </li>
            <li className={!servingBackup && serving ? "text-green-700" : ""}>
              Quand le principal se répare, l'état est réconcilié et il reprend la main (retour automatique).
            </li>
          </ol>
          {rem?.protection && (
            <div className="mt-3 inline-block text-sm font-semibold text-accent bg-lavsoft px-3 py-1 rounded-full">🛡️ Bouclier anti-DoS actif</div>
          )}
        </div>
      </div>

      {/* Journal des bascules */}
      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Journal des bascules</h2>
      <div className="bg-white rounded-2xl shadow p-5">
        <div className="max-h-72 overflow-auto text-sm divide-y divide-lavsoft">
          {events.length === 0 && <div className="py-2 text-ink/40">Aucun événement — le cluster est stable.</div>}
          {events.map((e, i) => (
            <div key={i} className="py-1.5 flex gap-3">
              <span className="text-ink/40 tabular-nums">{e.t}</span>
              <span className={kindColor[e.kind] || "text-ink/70"}>{e.label}</span>
            </div>
          ))}
        </div>
        {cluster?.answered_by && (
          <div className="mt-3 text-xs text-ink/40">Réponse fournie par le nœud : {cluster.answered_by}</div>
        )}
      </div>
    </div>
  );
}
