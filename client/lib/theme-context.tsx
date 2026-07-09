"use client";

import {
  createContext,
  useContext,
  useCallback,
  useEffect,
  useSyncExternalStore,
} from "react";

interface ThemeContextValue {
  dark: boolean;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  dark: false,
  toggle: () => {},
});

// Custom event so the current tab is notified of theme changes ("storage"
// only fires in *other* tabs).
const THEME_EVENT = "themechange";

function subscribe(callback: () => void): () => void {
  window.addEventListener(THEME_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(THEME_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

function getSnapshot(): boolean {
  return (localStorage.getItem("theme") ?? "light") === "dark";
}

function getServerSnapshot(): boolean {
  return false;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // localStorage is the source of truth. useSyncExternalStore renders the
  // server snapshot first (matching SSR) then swaps to the real value after
  // hydration — no mismatch, and no setState-in-effect.
  const dark = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const toggle = useCallback(() => {
    const isDark = (localStorage.getItem("theme") ?? "light") === "dark";
    localStorage.setItem("theme", isDark ? "light" : "dark");
    window.dispatchEvent(new Event(THEME_EVENT));
  }, []);

  useEffect(() => {
    document.body.style.background = dark ? "#0d0c13" : "#f0eef8";
    document.body.style.color = dark ? "#eceaf5" : "#18161f";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  return (
    <ThemeContext.Provider value={{ dark, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
