import { defineConfig } from "vite";
import { resolve } from "path";

/**
 * Vite config for the orochi-hub dashboard frontend.
 *
 * Big-bang migration from hand-written classic-script JS to TS+Vite.
 * Output is a single IIFE bundle that replaces the ~100 individual
 * <script> tags in hub/templates/hub/dashboard.html.
 *
 * IIFE format preserves the classic-script global semantics: each
 * module's top-level `var`/`function` becomes `window.*`-accessible,
 * so we don't have to refactor every cross-file reference to an import.
 */
export default defineConfig({
  root: __dirname,
  publicDir: false,
  base: "/static/hub/dist/",
  logLevel: "warn",

  build: {
    // Django's collectstatic will pick up dist/ from the normal app-static tree.
    outDir: resolve(__dirname, "../static/hub/dist"),
    emptyOutDir: true,
    manifest: true,
    // Avoid transforming dynamic imports into code-split chunks — we want
    // one big bundle for v0 of the migration.
    rollupOptions: {
      input: resolve(__dirname, "src/index.ts"),
      output: {
        format: "iife",
        name: "OrochiHub",
        entryFileNames: "orochi-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
        inlineDynamicImports: true,
      },
    },
    target: "es2020",
    sourcemap: true,
    minify: false,
  },
});
