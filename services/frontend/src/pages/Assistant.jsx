import { useEffect, useRef, useState } from "react";
import { askAssistant, assistantEvents } from "../api.js";

const SUGGESTIONS = [
  "Que fait le système en cas de déni de service ?",
  "Comment est traitée une injection SQL ?",
  "Que s'est-il passé récemment sur le serveur ?",
  "Quelle est la différence entre disponibilité et compromission ?",
];

// Coloration d'une ligne de log selon son contenu.
function logTone(line) {
  const l = line.toLowerCase();
  if (/(block|403|denied|attack|exfil|compromis|fail|error|5\d\d)/.test(l)) return "text-red-300";
  if (/(warn|canary|failover|bascule|promot)/.test(l)) return "text-amber-300";
  return "text-ink/50";
}

export default function Assistant() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [msgs, setMsgs] = useState([]);      // [{role:'user'|'bot', text, sources?}]
  const [events, setEvents] = useState([]);
  const scroller = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    let stop = false;
    const load = async () => { const e = await assistantEvents(); if (!stop) setEvents(e); };
    load();
    const t = setInterval(load, 10000);
    return () => { stop = true; clearInterval(t); };
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, loading]);

  async function ask(question) {
    const text = (question ?? q).trim();
    if (!text || loading) return;
    setQ("");
    setMsgs((m) => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const r = await askAssistant(text);
      setMsgs((m) => [...m, { role: "bot", text: r.answer, sources: r.sources || [] }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "bot", text: `Erreur : ${e.message || "assistant injoignable"}`, sources: [] }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-5xl mx-auto p-5">
      {/* Hero */}
      <div className="bg-gradient-to-br from-ink via-accent to-[#6C5CE7] text-white rounded-3xl p-6 shadow-xl mb-5">
        <div className="text-[11px] tracking-widest font-bold opacity-80">RESILIENCE-ALPHA · ASSISTANT IA</div>
        <h1 className="text-3xl font-black mt-1">Assistant opérateur</h1>
        <p className="text-sm opacity-85 mt-1 max-w-2xl">
          Modèle <b>local</b> (Ollama) + RAG sur la documentation ET les <b>logs serveur en direct</b> :
          il sait expliquer l'architecture, les procédures et ce qui se passe réellement.
        </p>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        {/* Chat */}
        <div className="lg:col-span-2 bg-white rounded-2xl shadow flex flex-col" style={{ minHeight: "28rem" }}>
          <div ref={scroller} className="flex-1 p-4 space-y-3 overflow-auto" style={{ maxHeight: "30rem" }}>
            {msgs.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-center text-ink/50 py-10">
                <div className="text-4xl mb-2">🤖</div>
                <div className="text-sm">Pose une question sur l'incident, l'architecture ou les procédures.</div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${m.role === "user" ? "bg-accent text-white rounded-br-sm" : "bg-lavsoft text-ink rounded-bl-sm"}`}>
                  <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>
                  {m.sources?.length > 0 && (
                    <div className="mt-2 text-[11px] opacity-70">📄 {m.sources.join(" · ")}</div>
                  )}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-lavsoft text-ink/60 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm animate-pulse">Le modèle local réfléchit…</div>
              </div>
            )}
            <div ref={endRef} />
          </div>
          {/* Suggestions + saisie */}
          <div className="border-t border-lavsoft p-3">
            {msgs.length === 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => ask(s)} className="text-xs bg-lavsoft text-accent px-3 py-1 rounded-full hover:bg-lav/40">{s}</button>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask()}
                placeholder="Écris ta question…"
                className="flex-1 border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent"
              />
              <button onClick={() => ask()} disabled={loading} className="bg-accent text-white font-semibold px-5 rounded-lg hover:bg-ink transition disabled:opacity-50">
                {loading ? "…" : "Envoyer"}
              </button>
            </div>
          </div>
        </div>

        {/* Événements serveur live (lus par le RAG) */}
        <div className="bg-ink text-white rounded-2xl shadow p-4 flex flex-col" style={{ maxHeight: "34rem" }}>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2.5 h-2.5 rounded-full bg-green-400 animate-pulse"></span>
            <div className="font-bold text-sm">Événements serveur (live)</div>
          </div>
          <div className="text-[11px] text-white/50 mb-3">Logs ingérés en direct par l'assistant (Loki) : erreurs, WAF, bascules…</div>
          <div className="flex-1 overflow-auto font-mono text-[11px] leading-relaxed space-y-1">
            {events.length === 0 && <div className="text-white/40">Aucun événement récent — trafic sain.</div>}
            {events.map((line, i) => {
              const [cont, ...rest] = line.split(": ");
              const body = rest.join(": ") || cont;
              return (
                <div key={i} className="break-words">
                  {rest.length > 0 && <span className="text-accent/90">{cont} </span>}
                  <span className={logTone(line)}>{body}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <p className="text-xs text-ink/40 mt-4">
        L'assistant aide à comprendre ; il lit la documentation et les logs, mais ne peut pas agir sur le système.
      </p>
    </div>
  );
}
