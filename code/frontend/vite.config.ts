import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Forward /api/* requests to the FastAPI backend during dev so the
    // frontend can use same-origin relative URLs (and we sidestep CORS).
    // Override the target by setting VITE_API_TARGET in .env.local.
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
