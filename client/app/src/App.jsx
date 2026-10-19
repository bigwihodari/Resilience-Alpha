import { Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./api.js";
import Login from "./pages/Login.jsx";
import Pay from "./pages/Pay.jsx";

function Protected({ children }) {
  return getToken() ? children : <Navigate to="/" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/pay" element={<Protected><Pay /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
