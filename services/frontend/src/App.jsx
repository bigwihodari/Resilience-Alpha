import { Routes, Route, Navigate, Link, useLocation } from "react-router-dom";
import { getToken, clearToken } from "./api.js";
import Login from "./pages/Login.jsx";
import Payment from "./pages/Payment.jsx";
import Cockpit from "./pages/Cockpit.jsx";

function Protected({ children }) {
  return getToken() ? children : <Navigate to="/" replace />;
}

function NavBar() {
  const loc = useLocation();
  if (loc.pathname === "/") return null;
  return (
    <nav className="bg-ink text-white px-5 py-3 flex items-center gap-6 shadow">
      <span className="font-extrabold tracking-tight">RESILIENCE-ALPHA</span>
      <Link className="text-sm hover:text-lav" to="/app">Paiement</Link>
      <Link className="text-sm hover:text-lav" to="/cockpit">Cockpit</Link>
      <button
        className="ml-auto text-sm bg-white/10 hover:bg-white/20 px-3 py-1 rounded"
        onClick={() => { clearToken(); window.location.href = "/"; }}
      >
        Déconnexion
      </button>
    </nav>
  );
}

export default function App() {
  return (
    <>
      <NavBar />
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/app" element={<Protected><Payment /></Protected>} />
        <Route path="/cockpit" element={<Protected><Cockpit /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
