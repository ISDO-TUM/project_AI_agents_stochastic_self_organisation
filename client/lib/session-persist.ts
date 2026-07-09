"use client";

// Tiny sessionStorage read/write helpers, defensive like mode-gate.tsx's
// localStorage usage (private browsing / storage-disabled tabs shouldn't throw).
// sessionStorage (not localStorage) is deliberate: board data should die with
// the tab, not linger like the persisted app-mode choice does.

export function loadSession<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function saveSession<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage unavailable or quota exceeded — state just won't survive navigation.
  }
}
