// Anonymous per-browser identity (the app has no auth). A UUID is generated
// once, kept in localStorage, and sent as the X-User-Id header on every API
// request so the backend only lists this browser's agents, files and run
// history. Clearing site data resets the identity (and orphans the old rows
// as shared/legacy data).
const STORAGE_KEY = "hive-user-id";

export function getUserId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    let id = window.localStorage.getItem(STORAGE_KEY);
    if (!id) {
      id = crypto.randomUUID();
      window.localStorage.setItem(STORAGE_KEY, id);
    }
    return id;
  } catch {
    // Storage unavailable (e.g. blocked cookies) → run unscoped, like before.
    return null;
  }
}

export function userIdHeaders(): Record<string, string> {
  const id = getUserId();
  return id ? { "X-User-Id": id } : {};
}
