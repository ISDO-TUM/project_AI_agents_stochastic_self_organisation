"use client";

import {
  createContext,
  useContext,
  useEffect,
  useCallback,
  useSyncExternalStore,
} from "react";
import { setLlmHeaders } from "@/lib/api";

export interface ApiKeys {
  openaiKey: string;
  anthropicKey: string;
  groqKey: string;
  geminiKey: string;
  proxyKey: string;
  openaiBaseUrl: string;
  anthropicBaseUrl: string;
  groqBaseUrl: string;
  geminiBaseUrl: string;
  // Ollama is local and keyless; only the endpoint is configurable (blank ->
  // server default of http://localhost:11434/v1).
  ollamaBaseUrl: string;
}

export const EMPTY_KEYS: ApiKeys = {
  openaiKey: "",
  anthropicKey: "",
  groqKey: "",
  geminiKey: "",
  proxyKey: "",
  openaiBaseUrl: "",
  anthropicBaseUrl: "",
  groqBaseUrl: "",
  geminiBaseUrl: "",
  ollamaBaseUrl: "",
};

const STORAGE_KEY = "llm-api-keys";

// Ollama runs locally and needs no key, so it is always advertised at this
// endpoint unless the user overrides it in the keys modal.
export const OLLAMA_DEFAULT_ENDPOINT = "http://localhost:11434/v1";

// Map ApiKeys -> X-LLM-* headers, omitting empty values.
export function apiKeyHeaders(keys: ApiKeys): Record<string, string> {
  const pairs: [string, string][] = [
    ["X-LLM-OpenAI-Key", keys.openaiKey],
    ["X-LLM-Anthropic-Key", keys.anthropicKey],
    ["X-LLM-Groq-Key", keys.groqKey],
    ["X-LLM-Gemini-Key", keys.geminiKey],
    ["X-LLM-Proxy-Key", keys.proxyKey],
    ["X-LLM-OpenAI-Base-Url", keys.openaiBaseUrl],
    ["X-LLM-Anthropic-Base-Url", keys.anthropicBaseUrl],
    ["X-LLM-Groq-Base-Url", keys.groqBaseUrl],
    ["X-LLM-Gemini-Base-Url", keys.geminiBaseUrl],
    ["X-LLM-Ollama-Base-Url", keys.ollamaBaseUrl || OLLAMA_DEFAULT_ENDPOINT],
  ];
  return Object.fromEntries(
    pairs.filter(([, v]) => v.trim().length > 0).map(([k, v]) => [k, v.trim()]),
  );
}

export function hasAnyProviderKey(keys: ApiKeys): boolean {
  return [
    keys.openaiKey,
    keys.anthropicKey,
    keys.groqKey,
    keys.geminiKey,
    keys.proxyKey,
  ].some((v) => v.trim().length > 0);
}

interface ApiKeysContextValue {
  keys: ApiKeys;
  setKeys: (keys: ApiKeys) => void;
  clearKeys: () => void;
  hasAnyKey: boolean;
}

const ApiKeysContext = createContext<ApiKeysContextValue>({
  keys: EMPTY_KEYS,
  setKeys: () => {},
  clearKeys: () => {},
  hasAnyKey: false,
});

// Custom event so the current tab is notified of key changes ("storage" only
// fires in *other* tabs).
const KEYS_EVENT = "apikeyschange";

function subscribe(callback: () => void): () => void {
  window.addEventListener(KEYS_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(KEYS_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

// Cache the parsed snapshot keyed on the raw string so useSyncExternalStore
// gets a stable reference while storage is unchanged (avoids render loops).
let cachedRaw: string | null = null;
let cachedKeys: ApiKeys = EMPTY_KEYS;

function getSnapshot(): ApiKeys {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    if (raw) {
      try {
        cachedKeys = {
          ...EMPTY_KEYS,
          ...(JSON.parse(raw) as Partial<ApiKeys>),
        };
      } catch {
        cachedKeys = EMPTY_KEYS;
      }
    } else {
      cachedKeys = EMPTY_KEYS;
    }
  }
  return cachedKeys;
}

function getServerSnapshot(): ApiKeys {
  return EMPTY_KEYS;
}

export function ApiKeysProvider({ children }: { children: React.ReactNode }) {
  // sessionStorage is the source of truth. useSyncExternalStore renders the
  // server snapshot first (matching SSR) then swaps to the stored value after
  // hydration — no mismatch, and no setState-in-effect.
  const keys = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setKeys = useCallback((next: ApiKeys) => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(KEYS_EVENT));
  }, []);

  const clearKeys = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new Event(KEYS_EVENT));
  }, []);

  // Keep the API layer's auth headers in sync with the current keys.
  useEffect(() => {
    setLlmHeaders(apiKeyHeaders(keys));
  }, [keys]);

  return (
    <ApiKeysContext.Provider
      value={{ keys, setKeys, clearKeys, hasAnyKey: hasAnyProviderKey(keys) }}
    >
      {children}
    </ApiKeysContext.Provider>
  );
}

export const useApiKeys = () => useContext(ApiKeysContext);
