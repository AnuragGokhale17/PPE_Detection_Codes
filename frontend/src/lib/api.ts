/** Thin fetch wrapper for the FastAPI backend (same-origin via the /api rewrite). */

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Detail = string | { code?: string; message?: string } | Array<{ msg: string; loc?: unknown[] }>;

function describe(detail: Detail | undefined, fallback: string): { message: string; code?: string } {
  if (!detail) return { message: fallback };
  if (typeof detail === "string") return { message: detail };
  if (Array.isArray(detail)) {
    // FastAPI validation errors
    return { message: detail.map((d) => d.msg.replace(/^Value error, /, "")).join(". "), code: "validation" };
  }
  return { message: detail.message ?? fallback, code: detail.code };
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });

  if (res.status === 204) return undefined as T;

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const fallback = res.status >= 500 ? "The server could not complete the request." : `Request failed (${res.status}).`;
    const { message, code } = describe((body as { detail?: Detail } | null)?.detail, fallback);
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      window.dispatchEvent(new CustomEvent("ppe:unauthorized"));
    }
    throw new ApiError(res.status, message, code);
  }
  return body as T;
}
