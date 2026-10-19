import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En dev local (hors Docker), on proxy vers les ports publiés par compose.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/auth": { target: "http://localhost:8001", changeOrigin: true, rewrite: (p) => p.replace(/^\/auth/, "") },
      "/api": { target: "http://localhost:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
