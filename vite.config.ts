import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: process.env.SERVER_URL || (process.env.VITE_API_PORT ? `http://127.0.0.1:${process.env.VITE_API_PORT}` : "http://127.0.0.1:8001"),
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
