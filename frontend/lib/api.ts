// In dev, the backend runs on port 8000. When port forwarding, the frontend is
// accessed at a different host — match the current origin's host & protocol so
// CORS and mixed-content rules don't block the request.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? (
  typeof window !== "undefined"
    ? `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
    : "http://localhost:8000/api/v1"
);

type Tokens = { access_token: string; refresh_token?: string | null; expires_in: number };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
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
    throw new ApiError(response.status, body.detail ?? "Request failed");
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
    throw new ApiError(response.status, error.detail);
  }
  authStore.set(await response.json());
}
