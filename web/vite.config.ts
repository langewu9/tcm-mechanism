import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(({ mode }) => {
  const target = loadEnv(mode, ".", "TCM_").TCM_API_PROXY_TARGET || "http://127.0.0.1:8020";
  return {
    publicDir: "../public",
    plugins: [react()],
    server: { proxy: {
      "^/api/": { target, changeOrigin: true },
      "/django-admin": { target, changeOrigin: true },
      "/accounts": { target, changeOrigin: true },
      "/static": { target, changeOrigin: true },
    } },
  };
});
