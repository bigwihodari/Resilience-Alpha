import { useEffect, useState, useRef } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { promInstant, promRange, scalar, orchStatus } from "../api.js";

const SERVICES = [
  { job: "api", label: "API paiement" },
  { job: "auth", label: "Authentification" },
  { job: "cadvisor", label: "Métriques conteneurs" },
  { job: "prometheus", label: "Supervision" },
];

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function rangeToSeries(result, mul = 1) {
  if (!result || !result.length) return [];
  return result[0].values.map(([t, v]) => ({ t: fmtTime(t), v: Math.round(parseFloat(v) * mul * 100) / 100 }));
}

export default function Cockpit() {
  const host = typeof window !== "undefined" ? window.location.hostname : "localhost";
  const [health, setHealth] = useState({});
  const [kpi, setKpi] = useState({ reqs: 0, p95: 0, c4xx: 0, c5xx: 0 });
  const [reqSeries, setReqSeries] = useState([]);
  const [latSeries, setLatSeries] = useState([]);
  const [ml, setMl] = useState({ score: 0, flag: false, trained: false });
  const [anomSeries, setAnomSeries] = useState([]);
  const [rem, setRem] = useState(null);
  const timer = useRef(null);

  async function refresh() {
    const [up, reqs, p95, c4xx, c5xx] = await Promise.all([
      promInstant("up"),
      promInstant('sum(rate(http_requests_total{job="api"}[1m]))'),
      promInstant('histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="auth"}[1m])) by (le))'),
      promInstant('sum(rate(http_requests_total{status="4xx"}[1m]))'),
      promInstant('sum(rate(http_requests_total{status="5xx"}[1m]))'),
    ]);
    const h = {};
    up.forEach((s) => { h[s.metric.job] = s.value[1] === "1"; });
    setHealth(h);
    setKpi({
      reqs: Math.round(scalar(reqs) * 10) / 10,
      p95: Math.round(scalar(p95) * 1000),
      c4xx: Math.round(scalar(c4xx) * 10) / 10,
      c5xx: Math.round(scalar(c5xx) * 10) / 10,
    });
    const [r1, r2] = await Promise.all([
      promRange('sum(rate(http_requests_total{job="auth"}[1m]))'),
      promRange('histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="auth"}[1m])) by (le))'),
    ]);
    setReqSeries(rangeToSeries(r1));
    setLatSeries(rangeToSeries(r2, 1000));

    // Détection ML (service detector, exposé à Prometheus)
    const [anom, flag, trained, anomRange] = await Promise.all([
      promInstant("anomaly_score"),
      promInstant("anomaly_flag"),
      promInstant("detector_trained"),
      promRange("anomaly_score"),
    ]);
    setMl({ score: Math.round(scalar(anom) * 10) / 10, flag: scalar(flag) === 1, trained: scalar(trained) === 1 });
    setAnomSeries(rangeToSeries(anomRange));

    // Moteur de remédiation
    setRem(await orchStatus());
  }

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, 5000);
    return () => clearInterval(timer.current);
  }, []);

  const Tile = ({ label, value, unit, tone }) => (
    <div className="bg-white rounded-2xl shadow p-4">
      <div className="text-xs text-ink/50 font-semibold uppercase tracking-wide">{label}</div>
      <div className={`text-3xl font-extrabold mt-1 ${tone || "text-ink"}`}>
        {value}<span className="text-base font-semibold text-ink/40 ml-1">{unit}</span>
      </div>
    </div>
  );

  const Chart = ({ title, data, color, unit }) => (
    <div className="bg-white rounded-2xl shadow p-4">
      <div className="font-bold mb-2">{title}</div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#EEF0F8" />
          <XAxis dataKey="t" tick={{ fontSize: 10, fill: "#8A86AE" }} minTickGap={40} />
          <YAxis tick={{ fontSize: 10, fill: "#8A86AE" }} width={44} />
          <Tooltip formatter={(v) => [`${v} ${unit}`, ""]} labelStyle={{ color: "#261E48" }} />
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto p-5">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="text-2xl font-extrabold">Cockpit de résilience</h1>
        <span className="ml-auto inline-flex items-center gap-2 text-sm bg-white px-3 py-1.5 rounded-full shadow">
          <span className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse"></span> Supervision active
        </span>
      </div>

      {/* État des systèmes */}
      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">État des systèmes</h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {SERVICES.map((s) => {
          const ok = health[s.job];
          return (
            <div key={s.job} className="bg-white rounded-2xl shadow p-4 flex items-center gap-3">
              <span className={`w-3 h-3 rounded-full ${ok ? "bg-green-500" : "bg-red-500"}`}></span>
              <div>
                <div className="font-semibold text-sm">{s.label}</div>
                <div className={`text-xs ${ok ? "text-green-600" : "text-red-600"}`}>{ok ? "en ligne" : "hors ligne"}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* KPIs */}
      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Indicateurs live</h2>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <Tile label="Débit API" value={kpi.reqs} unit="req/s" />
        <Tile label="Latence auth (p95)" value={kpi.p95} unit="ms" tone={kpi.p95 > 300 ? "text-amber-600" : "text-ink"} />
        <Tile label="Erreurs 4xx" value={kpi.c4xx} unit="/s" tone={kpi.c4xx > 5 ? "text-red-600" : "text-ink"} />
        <Tile label="Erreurs 5xx" value={kpi.c5xx} unit="/s" tone={kpi.c5xx > 0 ? "text-red-600" : "text-ink"} />
      </div>

      {/* Graphes */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Chart title="Débit auth (req/s)" data={reqSeries} color="#4B3FA6" unit="req/s" />
        <Chart title="Latence auth p95 (ms)" data={latSeries} color="#B8840F" unit="ms" />
      </div>

      {/* Détection par IA (P4) */}
      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Détection par intelligence artificielle</h2>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className={`rounded-2xl shadow p-5 text-center ${ml.flag ? "bg-red-50 border border-red-300" : "bg-white"}`}>
          <div className="text-xs text-ink/50 font-semibold uppercase tracking-wide">Score d'anomalie (Isolation Forest)</div>
          <div className={`text-5xl font-extrabold mt-2 ${ml.flag ? "text-red-600" : "text-green-600"}`}>
            {ml.trained ? ml.score : "—"}
          </div>
          <div className="mt-2">
            {!ml.trained ? (
              <span className="text-sm text-ink/50">🧠 apprentissage de la normale…</span>
            ) : ml.flag ? (
              <span className="inline-block text-sm font-bold text-red-700 bg-red-100 px-3 py-1 rounded-full">⚠ ANOMALIE DÉTECTÉE</span>
            ) : (
              <span className="inline-block text-sm font-bold text-green-700 bg-green-100 px-3 py-1 rounded-full">✓ Comportement normal</span>
            )}
          </div>
        </div>
        <div className="lg:col-span-2">
          <Chart title="Score d'anomalie (0–100)" data={anomSeries} color={ml.flag ? "#C2413C" : "#1E8E6A"} unit="" />
        </div>
      </div>

      {/* Remédiation autonome (P5) */}
      <h2 className="text-sm font-bold uppercase tracking-wide text-accent mb-2">Remédiation autonome</h2>
      {(() => {
        const st = rem?.state || "NORMAL";
        const steps = ["NORMAL", "REMEDIATING", "VERIFYING", "RECOVERED"];
        const labels = { NORMAL: "Surveillance", REMEDIATING: "Action", VERIFYING: "Vérification", RECOVERED: "Rétabli" };
        const idx = Math.max(0, steps.indexOf(st));
        const badge =
          st === "NORMAL" ? ["bg-green-100 text-green-700", "● Surveillance — normal"] :
          st === "RECOVERED" ? ["bg-green-100 text-green-700", "✓ Service rétabli (sous protection)"] :
          ["bg-amber-100 text-amber-700", "⟳ Remédiation en cours…"];
        const kindColor = { success: "text-green-700", alert: "text-red-700", error: "text-red-700", action: "text-accent", info: "text-ink/60" };
        return (
          <div className="bg-white rounded-2xl shadow p-5 mb-6">
            <div className="flex flex-wrap items-center gap-3 mb-4">
              <span className={`text-sm font-bold px-3 py-1 rounded-full ${badge[0]}`}>{badge[1]}</span>
              {rem?.protection && <span className="text-sm font-semibold text-accent bg-lavsoft px-3 py-1 rounded-full">🛡️ Bouclier actif</span>}
              {rem?.last_canary && (
                <span className={`text-sm px-3 py-1 rounded-full ${rem.last_canary.ok ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                  Canari : {rem.last_canary.ok ? `✓ OK (${rem.last_canary.latency_ms} ms)` : `✗ ${rem.last_canary.detail}`}
                </span>
              )}
            </div>
            {/* Stepper */}
            <div className="flex items-center gap-2 mb-4">
              {steps.map((s, i) => (
                <div key={s} className="flex-1 text-center">
                  <div className={`h-1.5 rounded-full ${i <= idx ? "bg-accent" : "bg-lavsoft"}`}></div>
                  <div className={`text-xs mt-1 ${i <= idx ? "text-accent font-semibold" : "text-ink/40"}`}>{labels[s]}</div>
                </div>
              ))}
            </div>
            {/* Timeline */}
            <div className="max-h-56 overflow-auto text-sm divide-y divide-lavsoft">
              {(rem?.timeline || []).slice().reverse().map((e, i) => (
                <div key={i} className="py-1.5 flex gap-3">
                  <span className="text-ink/40 tabular-nums">{e.t}</span>
                  <span className={kindColor[e.kind] || "text-ink/70"}>{e.label}</span>
                </div>
              ))}
              {(!rem || !rem.timeline || rem.timeline.length === 0) && (
                <div className="py-2 text-ink/40">En attente de l'orchestrateur…</div>
              )}
            </div>
          </div>
        );
      })()}

      {/* Outils avancés (repli, optionnel) */}
      <details className="bg-white/60 rounded-xl p-3 text-sm">
        <summary className="cursor-pointer text-ink/60 font-semibold">Outils avancés (optionnel)</summary>
        <div className="flex flex-wrap gap-2 mt-3">
          <a className="text-accent underline" href={`http://${host}:3000`} target="_blank" rel="noreferrer">Grafana</a>
          <a className="text-accent underline" href={`http://${host}:9090/targets`} target="_blank" rel="noreferrer">Prometheus</a>
          <a className="text-accent underline" href={`http://${host}:3000/explore`} target="_blank" rel="noreferrer">Logs (Loki)</a>
          <a className="text-accent underline" href={`http://${host}:8000/docs`} target="_blank" rel="noreferrer">API (docs)</a>
        </div>
      </details>
    </div>
  );
}
