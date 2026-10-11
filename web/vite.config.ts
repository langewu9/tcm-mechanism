import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  publicDir: "../public",
  plugins: [react()],
  server: { proxy: {
    "^/api/": { target: "http://127.0.0.1:8020", changeOrigin: true },
    "/django-admin": { target: "http://127.0.0.1:8020", changeOrigin: true },
    "/accounts": { target: "http://127.0.0.1:8020", changeOrigin: true },
    "/static": { target: "http://127.0.0.1:8020", changeOrigin: true },
  } },
});
