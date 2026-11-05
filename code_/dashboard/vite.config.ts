import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served under /admin/ next to the chat app (see deployment/nginx.conf).
export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
