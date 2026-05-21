"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
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
};

const STORAGE_KEY = "llm-api-keys";

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

export function ApiKeysProvider({ children }: { children: React.ReactNode }) {
  const [keys, setKeysState] = useState<ApiKeys>(() => {
    if (typeof window === "undefined") return EMPTY_KEYS;
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_KEYS;
    try {
      return { ...EMPTY_KEYS, ...(JSON.parse(raw) as Partial<ApiKeys>) };
    } catch {
      return EMPTY_KEYS;
    }
  });

  useEffect(() => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(keys));
    setLlmHeaders(apiKeyHeaders(keys));
  }, [keys]);

  const setKeys = useCallback((next: ApiKeys) => setKeysState(next), []);
  const clearKeys = useCallback(() => {
    setKeysState(EMPTY_KEYS);
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <ApiKeysContext.Provider
      value={{ keys, setKeys, clearKeys, hasAnyKey: hasAnyProviderKey(keys) }}
    >
      {children}
    </ApiKeysContext.Provider>
  );
}

export const useApiKeys = () => useContext(ApiKeysContext);
