"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, Account, AuthStart } from "@/lib/api";
import LoginModal from "@/components/LoginModal";

const PROVIDER_BADGE: Record<string, string> = {
  claude: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  codex: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  aiprimetech: "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200",
  grok: "bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200",
};

function agoLabel(iso: string | undefined, now: number): string {
  if (!iso) return "usage never checked";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `updated ${s}s ago`;
  if (s < 3600) return `updated ${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `updated ${Math.floor(s / 3600)}h ago`;
  return `updated ${Math.floor(s / 86400)}d ago`;
}

function UsageBars({ usage }: { usage: Account["usage_info"] }) {
  if (!usage?.limits?.length) return null;
  return (
    <div className="space-y-1.5">
      {usage.limits.map((l) => (
        <div key={l.label}>
          <div className="flex justify-between text-xs text-gray-600 dark:text-gray-300">
            <span>{l.label}</span>
            <span>
              {l.used_percent}%{l.resets ? ` · resets ${l.resets}` : ""}
            </span>
          </div>
          <div className="h-1.5 rounded bg-gray-200 dark:bg-gray-700">
            <div
              className={`h-1.5 rounded ${
                l.used_percent >= 90 ? "bg-red-500" : l.used_percent >= 70 ? "bg-amber-500" : "bg-blue-500"
              }`}
              style={{ width: `${Math.min(l.used_percent, 100)}%` }}
            />
          </div>
        </div>
      ))}
      {usage.account?.model && (
        <div className="text-[10px] text-gray-400">model {usage.account.model}</div>
      )}
    </div>
  );
}

function Chip({ ok, label }: { ok: boolean | null; label: string }) {
  const color =
    ok === null
      ? "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300"
      : ok
        ? "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
        : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${color}`}>{label}</span>;
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [login, setLogin] = useState<{ account: Account; auth: AuthStart } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const router = useRouter();
  const checkedOnce = useRef(false);

  const refresh = useCallback(() => api.listAccounts().then(setAccounts).catch(console.error), []);

  // Re-check auth for one account (or all) against the actual CLI, then re-list.
  const refreshAuth = useCallback(
    async (accts: Account[]) => {
      await Promise.allSettled(
        accts.filter((a) => a.status === "running").map((a) => api.authStatus(a.id)),
      );
      refresh();
    },
    [refresh],
  );

  useEffect(() => {
    api.listAccounts().then((accts) => {
      setAccounts(accts);
      if (!checkedOnce.current) {
        checkedOnce.current = true;
        refreshAuth(accts);
      }
    }).catch(console.error);
  }, [refreshAuth]);

  // Live display: re-fetch accounts (cheap) and tick the clock every 10s so
  // usage values and the "updated Xs ago" label stay current without the
  // Usage button. Actual captures run on the backend poller — a capture
  // boots the full TUI (~30s), so it can't run that often.
  useEffect(() => {
    const t = setInterval(() => {
      setNow(Date.now());
      refresh();
    }, 10000);
    return () => clearInterval(t);
  }, [refresh]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    try {
      await fn();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(null);
    }
    refresh();
  };

  const openTerminal = async (a: Account) => {
    const { session_id } = await api.createSession(a.id);
    router.push(`/terminal/${session_id}`);
  };

  const startLogin = async (a: Account) => {
    try {
      const auth = await api.authStart(a.id);
      setLogin({ account: a, auth });
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Accounts</h1>
        <Link href="/create" className="rounded bg-blue-600 px-4 py-2 text-white">
          + New account
        </Link>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {accounts.map((a) => {
          const info = a.auth_info ?? {};
          const running = a.status === "running";
          const loggedIn =
            a.auth_status === "logged_in" ? true : a.auth_status === "unknown" ? null : false;
          return (
            <div key={a.id} className={`rounded-lg border p-4 space-y-3 ${busy === a.id ? "opacity-50" : ""}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-baseline gap-2">
                  <Link href={`/accounts/${a.id}`} className="text-lg font-semibold text-blue-600">
                    {a.name}
                  </Link>
                  <span className="text-[10px] text-gray-400">{agoLabel(a.usage_info?.checked_at, now)}</span>
                </div>
                <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${PROVIDER_BADGE[a.provider]}`}>
                  {a.provider}
                </span>
              </div>

              <div className="flex gap-2">
                <Chip ok={running} label={running ? "running" : a.status} />
                <Chip
                  ok={loggedIn}
                  label={loggedIn === null ? "auth unknown" : loggedIn ? "logged in" : "logged out"}
                />
                {info.plan && <Chip ok={true} label={info.plan} />}
              </div>

              <div className="min-h-10 text-sm text-gray-600 dark:text-gray-300">
                {info.email && <div className="truncate">{info.email}</div>}
                {info.method && <div className="text-xs text-gray-400">via {info.method}</div>}
                {!info.email && !info.method && (
                  <div className="text-xs text-gray-400">
                    {loggedIn ? "" : "Not authenticated yet — start a login."}
                  </div>
                )}
              </div>

              <UsageBars usage={a.usage_info} />

              <div className="flex flex-wrap gap-2 text-sm">
                {!running ? (
                  <button
                    className="rounded border px-2 py-1"
                    onClick={() =>
                      act(a.id, () => api.container(a.id, "create").catch(() => {}).then(() => api.container(a.id, "start")))
                    }
                  >
                    ▶ Start
                  </button>
                ) : (
                  <>
                    <button className="rounded border px-2 py-1" onClick={() => act(a.id, () => api.container(a.id, "stop"))}>■ Stop</button>
                    <button className="rounded border px-2 py-1" onClick={() => act(a.id, () => api.container(a.id, "restart"))}>↻ Restart</button>
                    <button className="rounded border px-2 py-1" onClick={() => startLogin(a)}>🔑 Login</button>
                    <button className="rounded border px-2 py-1" onClick={() => openTerminal(a)}>⌨ Terminal</button>
                    <button className="rounded border px-2 py-1" onClick={() => act(a.id, () => refreshAuth([a]))}>⟳ Auth</button>
                    <button
                      className="rounded border px-2 py-1"
                      title="Boots the CLI headlessly to read limits — takes ~20-40s"
                      onClick={() => act(a.id, () => api.refreshUsage(a.id))}
                    >
                      📊 Usage
                    </button>
                  </>
                )}
                <button
                  className="ml-auto rounded border border-red-400 px-2 py-1 text-red-600"
                  onClick={() =>
                    confirm(`Delete ${a.name}, its container AND its auth/workspace volumes?`) &&
                    act(a.id, () => api.deleteAccount(a.id))
                  }
                >
                  Delete
                </button>
              </div>
            </div>
          );
        })}
      </div>
      {accounts.length === 0 && (
        <p className="text-gray-500">
          No accounts yet — <Link href="/create" className="text-blue-600">create one</Link>.
        </p>
      )}

      {login && (
        <LoginModal
          account={login.account}
          auth={login.auth}
          onClose={() => {
            setLogin(null);
            refreshAuth([login.account]); // pick up the fresh login immediately
          }}
        />
      )}
    </main>
  );
}
