#!/usr/bin/env node
// Package a recorded swarm run (a *.recording.json exported from the app) into a
// single self-contained, offline HTML file that replays the exact run.
//
//   pnpm --filter app standalone <run.recording.json> [-o out.html]
//
// With no output path, writes "<recording-basename>.html" next to the input.
import { build } from "vite";
import { fileURLToPath } from "node:url";
import { dirname, resolve, basename, join } from "node:path";
import { readFileSync, copyFileSync, existsSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const clientRoot = resolve(here, "..");
const configFile = resolve(clientRoot, "standalone/vite.config.ts");

function fail(msg) {
  console.error(`\n✖ ${msg}\n`);
  process.exit(1);
}

const args = process.argv.slice(2);
let input;
let out;
let snapshot = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === "-o" || args[i] === "--out") {
    out = args[++i];
  } else if (args[i] === "--snapshot") {
    snapshot = true;
  } else if (!input) {
    input = args[i];
  }
}

if (!input) {
  fail(
    "Usage: pnpm --filter app standalone <run.recording.json> [-o out.html]",
  );
}

const inputPath = resolve(input);
if (!existsSync(inputPath)) fail(`Recording not found: ${inputPath}`);

// Validate it parses and looks like a recording before spinning up a build.
let rec;
try {
  rec = JSON.parse(readFileSync(inputPath, "utf8"));
} catch (e) {
  fail(`Recording is not valid JSON: ${e.message}`);
}
if (!rec || !Array.isArray(rec.steps) || !rec.canvas) {
  fail("File does not look like a swarm recording (missing steps/canvas).");
}
if (rec.steps.length === 0) {
  console.warn("⚠ Recording has 0 steps — the replay will be empty.");
}

const outPath = out
  ? resolve(out)
  : join(
      dirname(inputPath),
      basename(inputPath)
        .replace(/\.recording\.json$/i, "")
        .replace(/\.json$/i, "") + ".html",
    );

console.log(`• Recording: ${inputPath} (${rec.steps.length} steps)`);
console.log(`• Building standalone player…`);

process.env.RECORDING_FILE = inputPath;
process.env.PLAYER_MODE = snapshot ? "snapshot" : "replay";
console.log(`• Mode: ${process.env.PLAYER_MODE}`);
await build({ configFile, logLevel: "warn" });

const built = resolve(clientRoot, "standalone/dist/index.html");
if (!existsSync(built))
  fail("Build did not produce standalone/dist/index.html");
copyFileSync(built, outPath);

console.log(`\n✔ Wrote self-contained player: ${outPath}`);
console.log("  Open it in any browser (double-click) — no server needed.\n");
