import { Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./api.js";
import Login from "./pages/Login.jsx";
import Dashboard from "./pages/Dashboard.jsx";

function Protected({ children }) {
  return getToken() ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      {/* Paiement = onglet du dashboard ; Chat & Dino = widgets flottants partout */}
      <Route path="/pay" element={<Navigate to="/dashboard" replace />} />
      <Route path="/chat" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dino" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
