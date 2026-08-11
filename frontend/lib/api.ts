import type { ChatMessage } from "@/lib/types";

// In dev, the backend runs on port 8000. When port forwarding, the frontend is
// accessed at a different host — match the current origin's host & protocol so
// CORS and mixed-content rules don't block the request.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? (
  typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
    : "http://localhost:8000/api/v1"
);

type Tokens = { access_token: string; refresh_token?: string | null; expires_in: number };

export interface StreamHandlers {
  onStatus?: (message: string) => void;
  onDelta?: (text: string) => void;
  onDone: (message: ChatMessage) => void;
  onError: (message: string) => void;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/**
 * FastAPI 422 responses return `detail` as an array of { loc, msg, type }
 * objects. Turn any detail shape into a readable message instead of letting
 * the raw array stringify to "[object Object]" in the UI.
 */
function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) => {
          if (item && typeof item === "object") {
            const record = item as { loc?: unknown; msg?: unknown };
            const field = Array.isArray(record.loc) ? String(record.loc[record.loc.length - 1]) : "";
            const msg = typeof record.msg === "string" ? record.msg : "";
            if (field && msg) return `${field}: ${msg}`;
            return msg || String(item);
          }
          return String(item);
        })
        .filter(Boolean);
      if (parts.length) return parts.join(" · ");
    }
  }
  return fallback;
}

export const authStore = {
  get accessToken() {
    return typeof window === "undefined" ? null : sessionStorage.getItem("meetai_access");
  },
  set(tokens: Tokens) {
    sessionStorage.setItem("meetai_access", tokens.access_token);
  },
  clear() {
    sessionStorage.removeItem("meetai_access");
  },
};

export async function refreshAccess(): Promise<boolean> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({}),
  });
  if (!response.ok) {
    authStore.clear();
    return false;
  }
  authStore.set(await response.json());
  return true;
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body) headers.set("Content-Type", "application/json");
  if (authStore.accessToken) headers.set("Authorization", `Bearer ${authStore.accessToken}`);
  const response = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store", credentials: "include" });
  if (response.status === 401 && retry && (await refreshAccess())) return api<T>(path, init, false);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new ApiError(response.status, errorMessage(body, "Request failed"));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function authenticate(
  mode: "login" | "register",
  body: Record<string, string>,
): Promise<void> {
  const response = await fetch(`${API_URL}/auth/${mode}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ ...body, client_type: "web" }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Authentication failed" }));
    throw new ApiError(response.status, errorMessage(error, "Authentication failed"));
  }
  authStore.set(await response.json());
}

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

function parseSseEvent(raw: string): SseEvent | null {
  let event = "message";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return null;
  }
}

async function postStream(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (authStore.accessToken) headers.set("Authorization", `Bearer ${authStore.accessToken}`);
  const init: RequestInit = {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify(body),
    signal,
  };
  let response = await fetch(`${API_URL}${path}`, init);
  if (response.status === 401 && (await refreshAccess())) {
    headers.set("Authorization", `Bearer ${authStore.accessToken}`);
    response = await fetch(`${API_URL}${path}`, init);
  }
  return response;
}

/**
 * POST to a Server-Sent Events endpoint and dispatch parsed events to handlers.
 *
 * EventSource only supports GET, so this uses fetch + ReadableStream. A
 * TextDecoder keeps multi-byte UTF-8 characters intact across chunk boundaries.
 */
export async function streamChat(
  path: string,
  body: { query: string },
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await postStream(path, body, signal);
  if (!response.ok || !response.body) {
    const error = await response
      .json()
      .catch(() => ({ detail: "Answer generation failed. Please try again." }));
    handlers.onError(errorMessage(error, "Answer generation failed. Please try again."));
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let receivedTerminal = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const sse = parseSseEvent(frame);
        if (!sse) continue;
        if (sse.event === "status") handlers.onStatus?.(String(sse.data.message ?? ""));
        else if (sse.event === "delta") handlers.onDelta?.(String(sse.data.text ?? ""));
        else if (sse.event === "done") {
          receivedTerminal = true;
          handlers.onDone(sse.data.message as ChatMessage);
        } else if (sse.event === "error") {
          receivedTerminal = true;
          handlers.onError(String(sse.data.message ?? "Answer generation failed. Please try again."));
        }
      }
    }
  } catch {
    receivedTerminal = true;
    if (!signal?.aborted) handlers.onError("Connection lost while generating the answer.");
  }
  if (!receivedTerminal && !signal?.aborted) {
    handlers.onError("Connection closed before the answer completed.");
  }
}
