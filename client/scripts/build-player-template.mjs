#!/usr/bin/env node
// Build the standalone player ONCE with no recording embedded, and drop it in
// public/ as `player-template.html`. The app fetches this at runtime and injects
// a recording into it to produce a shareable .html — so the browser never needs
// a bundler. Regenerate whenever the player/app code changes.
//
//   node scripts/build-player-template.mjs [--if-missing]
import { build } from "vite";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { copyFileSync, mkdirSync, existsSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const outFile = resolve(clientRoot, "public/player-template.html");

if (process.argv.includes("--if-missing") && existsSync(outFile)) {
  process.exit(0);
}

// No RECORDING_FILE → the injector is a no-op, so the template ships empty and
// renders whatever `window.__RECORDING__` is injected into it later.
delete process.env.RECORDING_FILE;
await build({
  configFile: resolve(clientRoot, "standalone/vite.config.ts"),
  logLevel: "warn",
});

mkdirSync(resolve(clientRoot, "public"), { recursive: true });
copyFileSync(resolve(clientRoot, "standalone/dist/index.html"), outFile);
console.log("✔ public/player-template.html");
