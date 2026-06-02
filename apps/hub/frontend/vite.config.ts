import { defineConfig } from "vite";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: __dirname,
  base: "/static/hub/dist/",
  build: {
    outDir: resolve(__dirname, "../static/hub/dist"),
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: resolve(__dirname, "src/index.ts"),
      output: {
        entryFileNames: "orochi-[hash].js",
        chunkFileNames: "orochi-[name]-[hash].js",
        assetFileNames: "orochi-[name]-[hash][extname]",
      },
    },
    target: "es2020",
    sourcemap: true,
    minify: false,
  },
});
