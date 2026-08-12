import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Cloudflare Pages build serves everything in dist/ as static files and runs
// functions/ as Pages Functions. During local `vite dev` the /api and /auth
// routes are handled by `wrangler pages dev`; see package.json pages:dev.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist" },
});
