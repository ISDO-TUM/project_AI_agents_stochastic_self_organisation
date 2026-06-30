// Browser-notification opt-in for swarm runs. A run can take a while, so the
// user can consent to a "your answer is ready" notification and choose whether
// the choice is remembered permanently ("always" → localStorage) or only for the
// current tab session ("session" → sessionStorage). All client-side; no backend.

export type NotifyScope = "always" | "session";

export interface NotifyPref {
  enabled: boolean;
  scope: NotifyScope;
}

const KEY = "swarm.notifyPref";

export function notificationsSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/**
 * The saved preference, or null if the user has never been asked. Checks the
 * durable store (localStorage) first, then the per-session one (sessionStorage),
 * so an "always" choice wins and a "session" choice is scoped to this tab.
 */
export function readNotifyPref(): NotifyPref | null {
  if (typeof window === "undefined") return null;
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      const raw = store.getItem(KEY);
      if (raw) return JSON.parse(raw) as NotifyPref;
    } catch {
      // Storage blocked (private mode) or malformed — treat as "not chosen".
    }
  }
  return null;
}

/**
 * Persist the choice. "always" goes to localStorage (survives new sessions);
 * "session" goes to sessionStorage (cleared when the tab/session ends). The other
 * store is cleared so the two scopes can never disagree.
 */
export function saveNotifyPref(enabled: boolean, scope: NotifyScope): void {
  if (typeof window === "undefined") return;
  try {
    const value = JSON.stringify({ enabled, scope } satisfies NotifyPref);
    if (scope === "always") {
      window.localStorage.setItem(KEY, value);
      window.sessionStorage.removeItem(KEY);
    } else {
      window.sessionStorage.setItem(KEY, value);
      window.localStorage.removeItem(KEY);
    }
  } catch {
    // Storage unavailable — the choice still applies for the current run.
  }
}

/** Ask the browser for permission. Must be called from a user gesture. */
export async function requestNotifyPermission(): Promise<NotificationPermission> {
  if (!notificationsSupported()) return "denied";
  if (Notification.permission !== "default") return Notification.permission;
  try {
    return await Notification.requestPermission();
  } catch {
    return Notification.permission;
  }
}

/**
 * Fire the "answer ready" notification — but only if the user consented, the
 * browser granted permission, and the tab is currently backgrounded (when it is
 * focused the in-app reveal overlay already serves, so a notification would just
 * be noise).
 */
export function fireAnswerNotification(answer: string): void {
  if (!notificationsSupported()) return;
  if (!readNotifyPref()?.enabled) return;
  if (Notification.permission !== "granted") return;
  if (typeof document !== "undefined" && !document.hidden) return;
  const body = answer.length > 140 ? `${answer.slice(0, 140)}…` : answer;
  try {
    const n = new Notification("Your swarm answer is ready", {
      body,
      tag: "swarm-final-answer",
    });
    n.onclick = () => {
      window.focus();
      n.close();
    };
  } catch {
    // Some browsers throw when constructed outside a service-worker context.
  }
}
