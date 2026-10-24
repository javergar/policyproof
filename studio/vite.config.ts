import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes into the Python package, which serves it; `npm run dev` proxies the API to a running studio
// (start one with `policyproof studio DOC --port 8765 --no-browser` and open the dev page with its `?t=` token).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/policyproof/studio/static", emptyOutDir: true, assetsDir: "assets" },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "node" },
});
