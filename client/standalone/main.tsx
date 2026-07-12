// Entry point for the standalone single-file player. Boots the real <App> into
// Market Hive replay mode from a recording embedded at build time as
// `window.__RECORDING__`. No backend, no router — fully offline.
import { createRoot } from "react-dom/client";
import { ThemeProvider } from "@/lib/theme-context";
import { ApiKeysProvider } from "@/lib/api-keys-context";
import { App } from "@/components/app";
import { isSwarmRecording } from "@/lib/recording";
import "@/app/globals.css";
import "./standalone.css";

// Belt-and-suspenders: neutralise any accidental backend call so the file works
// with no network. The App already skips its mount fetches in standalone mode,
// but a stray `/api/*` request must never hang or throw here.
const nativeFetch = window.fetch?.bind(window);
window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  if (/\/api\//.test(url) || /^https?:/i.test(url)) {
    return Promise.resolve(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  }
  return nativeFetch
    ? nativeFetch(input, init)
    : Promise.reject(new Error("offline"));
}) as typeof window.fetch;

const win = window as unknown as {
  __RECORDING__?: unknown;
  __PLAYER_MODE__?: string;
};
const rec = win.__RECORDING__;
const snapshot = win.__PLAYER_MODE__ === "snapshot";
const container = document.getElementById("root");
const root = createRoot(container!);

if (isSwarmRecording(rec)) {
  root.render(
    <ThemeProvider>
      <ApiKeysProvider>
        <App standalone recording={rec} snapshot={snapshot} />
      </ApiKeysProvider>
    </ThemeProvider>,
  );
} else {
  root.render(
    <div
      style={{
        padding: 24,
        fontFamily: "system-ui, sans-serif",
        color: "#eceaf5",
      }}
    >
      No recording embedded in this file.
    </div>,
  );
}
