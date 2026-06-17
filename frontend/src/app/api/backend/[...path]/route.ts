const BACKEND_API_URL = process.env.BACKEND_API_URL ?? "http://localhost:8000";

const TEXT_CONTENT_TYPES = new Set([
  "application/json",
  "text/",
  "application/x-www-form-urlencoded",
  "multipart/form-data",
]);

function isTextContentType(contentType: string | null): boolean {
  if (!contentType) return true;
  const normalized = contentType.toLowerCase().split(";")[0].trim();
  for (const prefix of TEXT_CONTENT_TYPES) {
    if (normalized === prefix || normalized.startsWith(prefix)) return true;
  }
  return false;
}

export const dynamic = "force-dynamic";

async function proxy(request: Request, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const incomingUrl = new URL(request.url);
  const backendUrl = new URL(path.join("/"), BACKEND_API_URL);
  backendUrl.search = incomingUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const authorization = request.headers.get("authorization");

  headers.set("Accept", request.headers.get("accept") ?? "application/json");
  if (contentType) headers.set("Content-Type", contentType);
  if (authorization) headers.set("Authorization", authorization);

  try {
    const response = await fetch(backendUrl, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });

    const responseContentType = response.headers.get("content-type") ?? "application/json";
    const responseHeaders = new Headers({
      "Content-Type": responseContentType,
    });

    // Preserve Content-Disposition for file downloads
    const disposition = response.headers.get("content-disposition");
    if (disposition) responseHeaders.set("Content-Disposition", disposition);

    // Read binary responses as ArrayBuffer to avoid UTF-8 corruption
    const body: BodyInit | null = isTextContentType(responseContentType)
      ? await response.text()
      : await response.arrayBuffer();

    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Backend request failed";
    return Response.json({ error: message }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
