const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS = API.replace(/^http/, "ws");

export interface Account {
  id: string;
  provider: "claude" | "codex" | "aiprimetech";
  name: string;
  container_name: string;
  status: string;
  auth_status: string;
  auth_info: { email?: string; plan?: string; method?: string; org?: string };
  usage_info: {
    limits?: { label: string; used_percent: number; resets?: string }[];
    account?: { plan?: string; email?: string; model?: string };
    checked_at?: string;
  };
  cpu_limit: number;
  memory_limit_mb: number;
  image: string;
  auth_volume: string;
  workspace_volume: string;
}

export interface AuthStart {
  status: string;
  provider: string;
  method: string;
  login_url: string | null;
  user_code: string | null;
  session_id: string;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  listAccounts: () => req<Account[]>("/accounts"),
  getAccount: (id: string) => req<Account>(`/accounts/${id}`),
  createAccount: (body: object) =>
    req<Account>("/accounts", { method: "POST", body: JSON.stringify(body) }),
  deleteAccount: (id: string) => req<void>(`/accounts/${id}`, { method: "DELETE" }),
  container: (id: string, action: "create" | "start" | "stop" | "restart") =>
    req(`/accounts/${id}/container/${action}`, { method: "POST" }),
  containerStatus: (id: string) => req<{ status: string }>(`/accounts/${id}/container/status`),
  logs: (id: string) => req<{ logs: string }>(`/accounts/${id}/container/logs`),
  authStart: (id: string) => req<AuthStart>(`/accounts/${id}/auth/start`, { method: "POST" }),
  authInput: (id: string, sessionId: string, value: string) =>
    req(`/accounts/${id}/auth/input?session_id=${sessionId}`, {
      method: "POST",
      body: JSON.stringify({ value }),
    }),
  authStatus: (id: string) => req<{ logged_in: boolean; raw: string }>(`/accounts/${id}/auth/status`),
  logout: (id: string) => req(`/accounts/${id}/auth/logout`, { method: "POST" }),
  createSession: (id: string) =>
    req<{ session_id: string }>(`/accounts/${id}/sessions`, { method: "POST" }),
  setupSession: (id: string) =>
    req<{ session_id: string; needs_callback_field: boolean }>(
      `/accounts/${id}/setup/session`,
      { method: "POST" },
    ),
  setupCallback: (id: string, value: string) =>
    req(`/accounts/${id}/setup/callback`, { method: "POST", body: JSON.stringify({ value }) }),
  setKey: (id: string, api_key: string, base_url: string) =>
    req(`/accounts/${id}/setkey`, { method: "POST", body: JSON.stringify({ api_key, base_url }) }),
  send: (sessionId: string, message: string) =>
    req(`/sessions/${sessionId}/send`, { method: "POST", body: JSON.stringify({ message }) }),
  sessionInput: (sessionId: string, value: string) =>
    req(`/sessions/${sessionId}/input`, { method: "POST", body: JSON.stringify({ value }) }),
  slash: (sessionId: string, command: string) =>
    req(`/sessions/${sessionId}/slash`, { method: "POST", body: JSON.stringify({ command }) }),
  closeSession: (sessionId: string) => req<void>(`/sessions/${sessionId}`, { method: "DELETE" }),
  usageHistory: (days = 31) =>
    req<{ account_id: string; name: string; provider: string; taken_at: string; label: string; used_percent: number }[]>(
      `/usage/history?days=${days}`,
    ),
  refreshUsage: (id: string) =>
    req<{ usage: Account["usage_info"]; raw: string }>(`/accounts/${id}/usage/refresh`, {
      method: "POST",
    }),
  exec: (id: string, message: string) =>
    req<{ exit_code: number; output: string }>(`/accounts/${id}/exec`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
};
