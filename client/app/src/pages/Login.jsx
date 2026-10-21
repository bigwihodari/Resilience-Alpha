import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, register, setSession } from "../api.js";

export default function Login() {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("adrien");
  const [password, setPassword] = useState("password123");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  async function submit(e) {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      if (mode === "register") await register(username, password);
      const r = await login(username, password);
      setSession(r.access_token, username);
      nav("/dashboard");
    } catch (e) {
      setErr(e.message || "Échec");
    } finally { setLoading(false); }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={submit} className="bg-white rounded-2xl shadow-xl p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-xs tracking-widest text-accent font-bold">RESILIENCE-ALPHA</div>
          <h1 className="text-2xl font-extrabold text-ink mt-1">Espace client</h1>
          <p className="text-sm text-ink/60">Payez vos amis en direct</p>
        </div>
        <label className="block text-sm font-semibold mb-1">Identifiant</label>
        <input className="w-full border border-lav rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-accent"
          value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        <label className="block text-sm font-semibold mb-1">Mot de passe</label>
        <input type="password" className="w-full border border-lav rounded-lg px-3 py-2 mb-5 focus:outline-none focus:ring-2 focus:ring-accent"
          value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        {err && <div className="text-sm text-red-600 mb-3">{err}</div>}
        <button disabled={loading} className="w-full bg-accent text-white font-semibold py-2.5 rounded-lg hover:bg-ink transition disabled:opacity-50">
          {loading ? "…" : (mode === "register" ? "Créer le compte" : "Se connecter")}
        </button>
        <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}
          className="w-full text-sm text-accent mt-3 hover:underline">
          {mode === "login" ? "Créer un nouveau compte" : "J'ai déjà un compte"}
        </button>
        <p className="text-xs text-ink/40 mt-3 text-center">Démo : adrien / hodari — mot de passe : password123</p>
      </form>
    </div>
  );
}
