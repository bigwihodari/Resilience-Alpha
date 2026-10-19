import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, setToken } from "../api.js";

export default function Login() {
  const [username, setUsername] = useState("alice");
  const [password, setPassword] = useState("password123");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      const r = await login(username, password);
      setToken(r.access_token);
      nav("/app");
    } catch (e) {
      setErr(e.message || "Échec de connexion");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={submit} className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-xs tracking-widest text-accent font-bold">RESILIENCE-ALPHA</div>
          <h1 className="text-2xl font-extrabold text-ink mt-1">Espace paiement</h1>
          <p className="text-sm text-ink/60">Plateforme de démonstration (fictive)</p>
        </div>
        <label className="block text-sm font-semibold mb-1">Identifiant</label>
        <input
          className="w-full border border-lav rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-accent"
          value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
        />
        <label className="block text-sm font-semibold mb-1">Mot de passe</label>
        <input
          type="password"
          className="w-full border border-lav rounded-lg px-3 py-2 mb-5 focus:outline-none focus:ring-2 focus:ring-accent"
          value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
        />
        {err && <div className="text-sm text-red-600 mb-3">{err}</div>}
        <button
          disabled={loading}
          className="w-full bg-accent text-white font-semibold py-2.5 rounded-lg hover:bg-ink transition disabled:opacity-50"
        >
          {loading ? "Connexion…" : "Se connecter"}
        </button>
        <p className="text-xs text-ink/40 mt-4 text-center">Démo : alice / password123</p>
      </form>
    </div>
  );
}
