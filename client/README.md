# Frontend — Stochastic Self-Organising Agents

Next.js 16 (App Router) · TypeScript · Tailwind CSS · Lucide React

The canvas UI for building, configuring, and simulating networks of AI agents.

---

## Stack

| Layer           | Technology                                          |
| --------------- | --------------------------------------------------- |
| Framework       | Next.js 16 (App Router, `'use client'`)             |
| Language        | TypeScript 6, strict mode                           |
| Styling         | Inline design tokens + Tailwind CSS v4              |
| Icons           | Lucide React (via custom `LIcon` wrapper)           |
| Fonts           | Space Grotesk · JetBrains Mono (`next/font/google`) |
| Package manager | pnpm (workspace root)                               |

---

## Project structure

```
app/
├── app/
│   ├── globals.css        # Tailwind import + keyframe animations
│   ├── layout.tsx         # Font loading, suppressHydrationWarning
│   └── page.tsx           # Entry point → <App />
├── components/
│   ├── app.tsx            # Root: all state, reducer, layout wiring
│   ├── toolbar.tsx        # Floating top pill (run/stop, add, export, theme)
│   ├── prompt-bar.tsx     # Floating bottom pill (simulation prompt input)
│   ├── context-menu.tsx   # Generic right-click menu
│   ├── log-wall.tsx       # Collapsible simulation log feed
│   ├── tweaks-panel.tsx   # Settings panel (grid, particles, labels…)
│   ├── canvas/
│   │   ├── index.tsx      # Pan/zoom SVG canvas, drag-to-connect
│   │   ├── agent-node.tsx # Draggable agent node
│   │   ├── source-node.tsx# Draggable source node
│   │   ├── edge-layer.tsx # Animated SVG edges + particles
│   │   └── minimap.tsx    # Thumbnail overview
│   └── panels/
│       ├── agent-panel.tsx      # Create / edit agent side panel
│       ├── source-panel.tsx     # Create / edit source side panel
│       └── panel-primitives.tsx # Shared form controls (FInput, FSelect, FBtn…)
└── lib/
    ├── api.ts             # Typed fetch client for /agents REST endpoints
    ├── icons.tsx          # LIcon wrapper + TOOL_ICON map
    ├── simulation.ts      # Simulation step generator (stub)
    ├── theme.ts           # Design-token system (light / dark, burgundy accent)
    ├── types.ts           # All TypeScript interfaces
    └── utils.ts           # uuid, autoLayout, PROVIDERS, TOOLS constants
```

---

## Getting started

From the **repo root**:

```bash
pnpm dev          # starts Next.js on :3000 and FastAPI on :8000 concurrently
```

Or run the frontend alone:

```bash
cd app
pnpm dev          # http://localhost:3000
```

Type-check only (no emit):

```bash
pnpm typecheck
```

---

## Environment variables

| Variable              | Default                 | Description                      |
| --------------------- | ----------------------- | -------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL for the FastAPI backend |

Set in `.env` at the repo root (created by `./scripts/setup.sh`).

---

## API integration

The frontend communicates with the backend via `lib/api.ts`. All functions are typed end-to-end and map between frontend camelCase and backend snake_case automatically.

| Function             | Method   | Endpoint       |
| -------------------- | -------- | -------------- |
| `fetchAgents()`      | `GET`    | `/agents`      |
| `createAgent(agent)` | `POST`   | `/agents`      |
| `updateAgent(agent)` | `PATCH`  | `/agents/{id}` |
| `deleteAgentApi(id)` | `DELETE` | `/agents/{id}` |

If the API is unreachable, all operations fall back to local-only state — the canvas remains fully functional offline.

> Sources are canvas-only for now (no `/sources` backend routes yet).

---

## Design system

All colours and spacing live in `lib/theme.ts`. Call `getTheme(dark: boolean)` to get a token object:

```ts
const t = getTheme(dark);
// t.bg, t.pill, t.pillBorder, t.text, t.textSub, t.textDim,
// t.border, t.borderHi, t.inputBg, t.hover, t.dotColor
```

Accent constants:

```ts
BURG; // '#8B1A2F'  — primary burgundy
BURG_LT; // '#C4374F'  — hover / lighter variant
BURG_DIM; // 'rgba(139,26,47,0.13)' — subtle fill
BURG_GLOW; // 'rgba(139,26,47,0.3)'  — glow / shadow
```

---

## Keyboard shortcuts

| Key                    | Action                        |
| ---------------------- | ----------------------------- |
| `Escape`               | Close panel / menu / deselect |
| `Delete` / `Backspace` | Delete selected node or edge  |

---

## Canvas interactions

| Interaction                | Action                      |
| -------------------------- | --------------------------- |
| Click node                 | Select                      |
| Double-click node          | Open edit panel             |
| Drag node                  | Move                        |
| Drag connect-handle → node | Create edge                 |
| Click edge                 | Select edge                 |
| Right-click node           | Edit / Delete menu          |
| Right-click canvas         | Add Agent / Add Source menu |
| Scroll                     | Zoom                        |
| Drag canvas background     | Pan                         |
