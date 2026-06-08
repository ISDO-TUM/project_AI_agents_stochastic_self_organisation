/**
 * Per-browser data owner id.
 *
 * Authentication is out of scope, but the backend still scopes each user's data
 * (agents, knowledge files, simulation history) so one browser never sees
 * another's. We generate a random id once, persist it in localStorage, and send
 * it as the `X-Owner-Id` header on every API request (see `lib/api.ts`).
 *
 * This is isolation, not authentication — the id is client-side and could be
 * edited by its owner. It is enough here because sharing is not a feature and
 * the ids are unguessable random UUIDs. The matching server logic lives in
 * `server/owner.py`.
 */

const STORAGE_KEY = "data-owner-id";

let cached: string | null = null;

/** Return this browser's owner id, generating and persisting one on first use. */
export function getOwnerId(): string {
  if (cached) return cached;
  // request() only runs in the browser, but guard SSR so importing this module
  // during prerender never throws. The empty id maps to the server's shared
  // bucket and is never actually sent from a real client request.
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, id);
  }
  cached = id;
  return id;
}
