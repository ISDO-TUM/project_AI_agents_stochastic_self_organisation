import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");

/**
 * Inject the recording (path in RECORDING_FILE) as `window.__RECORDING__` into
 * the HTML at build time, so viteSingleFile inlines it with everything else.
 */
function injectRecording(): Plugin {
  return {
    name: "inject-recording",
    transformIndexHtml(html) {
      const file = process.env.RECORDING_FILE;
      if (!file) return html;
      const json = readFileSync(resolve(file), "utf8");
      // Escape `<` so a value containing "</script>" can't break out of the tag.
      const safe = json.replace(/</g, "\\u003c");
      const mode =
        process.env.PLAYER_MODE === "snapshot" ? "snapshot" : "replay";
      const tag = `<script>window.__RECORDING__ = ${safe};window.__PLAYER_MODE__ = ${JSON.stringify(
        mode,
      )};</script>`;
      // Inject at the placeholder (see standalone/index.html) rather than
      // </head>: the inlined app bundle itself contains the string "</head>",
      // so a naive replace could land inside the JS and corrupt it.
      return html.replace("<!--RECORDING-SLOT-->", tag);
    },
  };
}

export default defineConfig({
  root: here,
  // Everything is inlined into one HTML file, so relative asset URLs are fine.
  base: "./",
  plugins: [react(), tailwindcss(), injectRecording(), viteSingleFile()],
  resolve: {
    alias: [
      // Next's `next/link` has no meaning offline — render a plain anchor.
      { find: /^next\/link$/, replacement: resolve(here, "shims/link.tsx") },
      // Mirror the Next `@/*` -> client-root path mapping (keep this last so the
      // more specific `next/link` rule wins first).
      { find: /^@\//, replacement: `${clientRoot}/` },
    ],
  },
  define: {
    // Next-only env the app reads; empty base = same-origin (never hit offline).
    "process.env.NEXT_PUBLIC_API_URL": '""',
    "process.env.NODE_ENV": '"production"',
  },
  build: {
    outDir: resolve(here, "dist"),
    emptyOutDir: true,
    // Inline every asset; viteSingleFile folds the JS/CSS into index.html.
    assetsInlineLimit: 100 * 1024 * 1024,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 100 * 1024 * 1024,
  },
});
