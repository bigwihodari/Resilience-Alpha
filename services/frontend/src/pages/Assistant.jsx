import { useState } from "react";
import { askAssistant } from "../api.js";

const SUGGESTIONS = [
  "Que fait le système en cas de déni de service ?",
  "Comment est traitée une injection SQL ?",
  "Que dois-je regarder dans le cockpit pendant un incident ?",
  "Quelle est la différence entre disponibilité et compromission ?",
];

export default function Assistant() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState(null);
  const [err, setErr] = useState("");

  async function ask(question) {
    const text = (question ?? q).trim();
    if (!text) return;
    setQ(text);
    setLoading(true);
    setErr("");
    setResp(null);
    try {
      setResp(await askAssistant(text));
    } catch (e) {
      setErr(e.message || "Erreur");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-5">
      <h1 className="text-2xl font-extrabold">Assistant opérateur</h1>
      <p className="text-ink/60 mb-5">
        Pose une question sur l'incident, l'architecture ou les procédures. Réponses
        générées par un modèle <b>local</b> (Ollama) appuyé sur la documentation du projet (RAG).
      </p>

      <div className="bg-white rounded-2xl shadow p-5">
        <div className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder="Ex. Comment le système réagit-il à une attaque ?"
            className="flex-1 border border-lav rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-accent"
          />
          <button
            onClick={() => ask()}
            disabled={loading}
            className="bg-accent text-white font-semibold px-5 rounded-lg hover:bg-ink transition disabled:opacity-50"
          >
            {loading ? "…" : "Demander"}
          </button>
        </div>

        <div className="flex flex-wrap gap-2 mt-3">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => ask(s)}
              className="text-xs bg-lavsoft text-accent px-3 py-1 rounded-full hover:bg-lav/40">
              {s}
            </button>
          ))}
        </div>

        {loading && <div className="mt-5 text-ink/50 text-sm animate-pulse">Le modèle local réfléchit… (peut prendre quelques secondes)</div>}
        {err && <div className="mt-5 text-red-600 text-sm">{err}</div>}

        {resp && (
          <div className="mt-5">
            <div className="whitespace-pre-wrap text-ink leading-relaxed">{resp.answer}</div>
            {resp.sources?.length > 0 && (
              <div className="mt-3 text-xs text-ink/50">
                Sources : {resp.sources.join(" · ")}
              </div>
            )}
          </div>
        )}
      </div>

      <p className="text-xs text-ink/40 mt-4">
        L'assistant aide à comprendre ; il ne peut pas agir sur le système (lecture de la documentation uniquement).
      </p>
    </div>
  );
}
