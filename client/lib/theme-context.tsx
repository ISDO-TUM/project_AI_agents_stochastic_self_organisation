"use client";

import { createContext, useContext, useState, useEffect } from "react";

interface ThemeContextValue {
  dark: boolean;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  dark: false,
  toggle: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Start with the server-consistent default; read the persisted value after
  // mount so server and client render identically on first paint (no hydration
  // mismatch).
  const [dark, setDark] = useState<boolean>(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setDark((localStorage.getItem("theme") ?? "light") === "dark");
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    localStorage.setItem("theme", dark ? "dark" : "light");
    document.body.style.background = dark ? "#060608" : "#f0eef8";
    document.body.style.color = dark ? "#eceaf5" : "#18161f";
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark, mounted]);

  return (
    <ThemeContext.Provider value={{ dark, toggle: () => setDark((x) => !x) }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
