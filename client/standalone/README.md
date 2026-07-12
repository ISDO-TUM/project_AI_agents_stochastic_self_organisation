# Standalone single-file player

Packages a **recorded Market Hive run** into one self-contained, offline HTML
file — canvas, blackboard, popups and the final-answer overlay — with no backend
and no network. Two modes (set via `window.__PLAYER_MODE__`):

- **snapshot** — builds the final board instantly (all draft + confirmed
  contributions), answer overlay dismissed so the columns are front and centre.
- **replay** — animates the run from the start.

## Usage

**From the UI (one click):** toolbar → **Recording** → **Save web page (.html)**.
The app fetches the pre-built template `public/player-template.html` and injects
the recording into it in the browser — no build step. The template is produced by
`scripts/build-player-template.mjs` (run automatically by `predev`; force a
rebuild with `pnpm --filter app build:player`).

**From the CLI:** starting from a `*.recording.json` (toolbar → Recording →
**Save data (.json)**):

```bash
pnpm --filter app standalone path/to/run.recording.json [-o out.html]
```

Writes `<name>.html` next to the recording (or the `-o` path). Double-click to
open in any browser. Both paths inject the recording at the `<!--RECORDING-SLOT-->`
placeholder — the UI in the browser, the CLI at build time — for the same result.

## How it works

- The recording (`lib/recording.ts`) is the verbatim SSE step stream of a run
  plus the canvas (agents/sources/edges) it ran against.
- The player reuses the **real** `components/app.tsx` in a `standalone` mode
  (no mode gate, no backend fetches, editing/nav hidden). `useSwarmRun`'s
  `startFromRecording` replays the steps through the _same_ reducer a live run
  uses, so the board and every popup render identically.
- `main.tsx` mounts `<App standalone recording={window.__RECORDING__} />`. The
  recording is injected into the HTML at build time by `vite.config.ts`
  (`RECORDING_FILE` env → `injectRecording` plugin), and everything is inlined
  into a single file by `vite-plugin-singlefile`.

## Files

- `vite.config.ts` — Vite build: React + Tailwind v4 + single-file, `@/*` alias
  to the client root, a `next/link` shim, and the recording injector.
- `main.tsx` — entry; wraps `<App>` in the Theme/ApiKeys providers and blocks any
  stray `/api` request so the file is fully offline.
- `shims/link.tsx` — offline replacement for `next/link` (renders a plain `<a>`).
- `standalone.css` — font-variable fallbacks the Next layout would normally set.
- `../scripts/make-standalone.mjs` — the `pnpm --filter app standalone` CLI.
