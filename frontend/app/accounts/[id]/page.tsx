"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, Account } from "@/lib/api";

export default function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const [account, setAccount] = useState<Account | null>(null);
  const [logs, setLogs] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getAccount(id).then(setAccount).catch(console.error);
    api.logs(id).then((r) => setLogs(r.logs)).catch(() => {});
  }, [id]);

  if (!account) return <main className="p-8">Loading…</main>;

  // Credit-safe: sends only /usage (claude) or /status (codex), which are
  // free TUI commands — never a prompt that would consume inference credits.
  const refreshUsage = async () => {
    setBusy(true);
    try {
      const r = await api.refreshUsage(id);
      setOutput(r.raw);
      setAccount(await api.getAccount(id));
    } catch (e) {
      setOutput(String(e));
    } finally {
      setBusy(false);
    }
  };

  const Row = ({ k, v }: { k: string; v: string | number }) => (
    <tr className="border-b"><td className="p-2 font-medium">{k}</td><td className="p-2 font-mono">{v}</td></tr>
  );

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-8">
      <h1 className="text-2xl font-bold">{account.name}</h1>
      <table className="w-full text-sm">
        <tbody>
          <Row k="Provider" v={account.provider} />
          <Row k="Container" v={account.container_name} />
          <Row k="Image" v={account.image} />
          <Row k="Auth volume" v={account.auth_volume} />
          <Row k="Workspace volume" v={account.workspace_volume} />
          <Row k="Container status" v={account.status} />
          <Row k="Auth status" v={account.auth_status} />
          {account.auth_info?.email && <Row k="Email" v={account.auth_info.email} />}
          {account.auth_info?.plan && <Row k="Plan" v={account.auth_info.plan} />}
          {account.auth_info?.method && <Row k="Auth method" v={account.auth_info.method} />}
          {account.auth_info?.org && <Row k="Organization" v={account.auth_info.org} />}
          <Row k="CPU limit" v={account.cpu_limit} />
          <Row k="Memory limit (MB)" v={account.memory_limit_mb} />
        </tbody>
      </table>

      <div className="flex items-center gap-3">
        <button
          className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
          onClick={refreshUsage}
          disabled={busy || account.status !== "running"}
        >
          {busy ? "Reading…" : `Refresh usage (${account.provider === "claude" ? "/usage" : "/status"})`}
        </button>
        <span className="text-xs text-gray-400">free — no credits consumed</span>
      </div>
      {account.usage_info?.limits?.length ? (
        <div className="space-y-1">
          {account.usage_info.limits.map((l) => (
            <div key={l.label} className="text-sm">
              <b>{l.label}</b>: {l.used_percent}% used{l.resets ? ` · resets ${l.resets}` : ""}
            </div>
          ))}
        </div>
      ) : null}
      {output && <pre className="overflow-x-auto rounded bg-gray-100 p-4 text-xs dark:bg-gray-800">{output}</pre>}

      <h2 className="font-bold">Container logs</h2>
      <pre className="max-h-64 overflow-auto rounded bg-gray-100 p-4 text-xs dark:bg-gray-800">{logs || "(empty)"}</pre>
    </main>
  );
}
