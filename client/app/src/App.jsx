import { Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./api.js";
import Login from "./pages/Login.jsx";
import Pay from "./pages/Pay.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Chat from "./pages/Chat.jsx";
import Dino from "./pages/Dino.jsx";

function Protected({ children }) {
  return getToken() ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
      <Route path="/pay" element={<Protected><Pay /></Protected>} />
      <Route path="/chat" element={<Protected><Chat /></Protected>} />
      <Route path="/dino" element={<Protected><Dino /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
