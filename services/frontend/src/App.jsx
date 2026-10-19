import { Routes, Route, Navigate, Link, useLocation } from "react-router-dom";
import { getToken, clearToken } from "./api.js";
import Login from "./pages/Login.jsx";
import Payment from "./pages/Payment.jsx";
import Cockpit from "./pages/Cockpit.jsx";
import Assistant from "./pages/Assistant.jsx";

function Protected({ children }) {
  return getToken() ? children : <Navigate to="/" replace />;
}

function NavBar() {
  const loc = useLocation();
  if (loc.pathname === "/") return null;
  const link = (to, label) => (
    <Link className="text-sm hover:text-lav" to={to}>{label}</Link>
  );
  return (
    <nav className="bg-ink text-white px-5 py-3 flex items-center gap-6 shadow">
      <Link to="/cockpit" className="font-extrabold tracking-tight">RESILIENCE-ALPHA</Link>
      {link("/cockpit", "Cockpit")}
      {link("/pay", "Paiement")}
      {link("/assistant", "Assistant")}
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
        <Route path="/cockpit" element={<Protected><Cockpit /></Protected>} />
        <Route path="/pay" element={<Protected><Payment /></Protected>} />
        <Route path="/assistant" element={<Protected><Assistant /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
