const FALLBACK = "/api/backend";

function resolveApiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL;

  // No env var set → use the Next.js rewrite proxy path (default)
  if (!raw) return FALLBACK;

  // Relative path (starts with /) — correct: goes through the Next.js proxy,
  // which resolves the backend URL server-side (inside Docker network).
  if (raw.startsWith("/")) return raw;

  // Absolute URL — validate the hostname so Docker service names
  // (e.g. "http://backend:8000") never leak to the browser.
  try {
    const url = new URL(raw);
    const { hostname } = url;

    // Docker Compose service names are single-label (no dots, not "localhost")
    // and cannot be resolved by the browser's DNS.
    if (!hostname.includes(".") && hostname !== "localhost") {
      console.warn(
        `[dmp] NEXT_PUBLIC_API_URL="${raw}" uses Docker hostname "${hostname}" ` +
          "which is unresolvable from the browser. " +
          `Falling back to "${FALLBACK}". ` +
          `Set NEXT_PUBLIC_API_URL=${FALLBACK} to use the Next.js rewrite proxy.`,
      );
      return FALLBACK;
    }
  } catch {
    // Invalid URL — fall back to the proxy path
    return FALLBACK;
  }

  return raw;
}

/**
 * Base URL for all API requests.
 *
 * Must always be a **relative** path (e.g. `/api/backend`) so the browser
 * sends requests through the Next.js rewrite proxy. The proxy (configured
 * in `next.config.ts` via `BACKEND_API_URL`) resolves the actual backend
 * URL server-side, where Docker DNS is available.
 *
 * Never set this to an absolute URL containing a Docker service name — the
 * browser cannot resolve those hostnames.
 */
export const API_BASE = resolveApiBase();
