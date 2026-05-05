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
  const [dark, setDark] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return (localStorage.getItem("theme") ?? "light") === "dark";
  });

  useEffect(() => {
    localStorage.setItem("theme", dark ? "dark" : "light");
    document.body.style.background = dark ? "#060608" : "#f0eef8";
    document.body.style.color = dark ? "#eceaf5" : "#18161f";
  }, [dark]);

  return (
    <ThemeContext.Provider value={{ dark, toggle: () => setDark((x) => !x) }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
