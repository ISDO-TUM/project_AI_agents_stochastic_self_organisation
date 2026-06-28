import type { NextRequest } from "next/server";

/**
 * Streaming proxy for `POST /api/simulation/run`.
 *
 * Why this file exists: the catch-all `rewrites()` proxy in `next.config.ts`
 * (`/api/:path*` → `INTERNAL_API_URL`) **buffers** streamed responses — Next's
 * rewrite proxy waits for the upstream response to finish before forwarding it
 * (vercel/next.js#66263). That turns the swarm run's incremental `text/event-stream`
 * into a single blob delivered at the end, so the UI only ever showed the final
 * result instead of each step as it happened.
 *
 * A Route Handler pipes the upstream body straight through, so every SSE frame
 * reaches the browser the moment the backend flushes it. Route handlers are
 * matched before `afterFiles` rewrites, so this takes over only this exact path;
 * every other `/api/*` request still goes through the rewrite unchanged.
 *
 * The same endpoint serves both engines: swarm runs (engine="swarm") return a
 * live `text/event-stream`, topology runs return a one-shot JSON object. Both are
 * forwarded verbatim — passing `upstream.body` through works for either.
 */

// Never cache or statically optimize — required for streaming to work at all.
export const dynamic = "force-dynamic";
// Node runtime forwards raw bytes without edge transforms.
export const runtime = "nodejs";
export const fetchCache = "force-no-store";

const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL ?? "http://localhost:8000";

// Hop-by-hop / proxy-managed request headers we must not forward upstream.
// `accept-encoding` is dropped so the backend answers with identity encoding and
// nothing re-buffers the stream to compress it.
const STRIP_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "accept-encoding",
]);

export async function POST(req: NextRequest): Promise<Response> {
  // Forward the caller's headers (Content-Type + any BYOK credential headers)
  // minus the hop-by-hop ones the proxy must manage itself.
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!STRIP_REQUEST_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });

  const upstream = await fetch(`${INTERNAL_API_URL}/api/simulation/run`, {
    method: "POST",
    headers,
    body: await req.text(),
    cache: "no-store",
  });

  // Forward the body verbatim and defeat every buffering layer between here and
  // the browser: `no-transform` stops gzip from batching frames, and
  // `X-Accel-Buffering: no` tells nginx / the Railway edge to flush immediately.
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ??
        "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
