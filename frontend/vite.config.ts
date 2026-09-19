import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the FastAPI backend (Phase 1-2) on :8003.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: { "/api": { target: "http://127.0.0.1:8003", changeOrigin: true } },
  },
});
