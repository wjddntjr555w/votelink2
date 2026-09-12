/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 개발 중에는 /api 를 FastAPI(기본 8420)로 프록시한다. 빌드 결과물은
// votelink/web/app.py 가 같은 오리진에서 정적 서빙하므로 프로덕션에선 프록시가 필요 없다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8420",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
