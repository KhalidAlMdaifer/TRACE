import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The api runs separately (uvicorn app.api.main:app --port 8000); the dev server proxies to
// it so the session cookie is same-origin.
const api = process.env.TRACE_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: Number(process.env.PORT ?? 5173), strictPort: true, proxy: { "/api": { target: api, changeOrigin: false } } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
