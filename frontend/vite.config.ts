import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev фронт ходит на backend напрямую через прокси.
// В проде статику отдаёт nginx, он же проксирует /api.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
