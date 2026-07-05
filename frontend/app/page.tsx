"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Account } from "@/lib/api";
import { C, Stat, TimeSeries } from "@/components/dashboard";

type HistoryRow = {
  account_id: string;
  name: string;
  provider: string;
  taken_at: string;
  label: string;
  used_percent: number;
};

const SESSION_RE = /session|5h/i;
const WEEKLY_ALL_RE = /all models/i;
const WEEKLY_RE = /week/i;

function daysInCurrentMonth(): number {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
}

// Bucket snapshots into day-of-current-month. Session/5h → daily peak;
// weekly → last snapshot of the day (prefer the "all models" gauge).
function aggregate(rows: HistoryRow[], accountId: string) {
  const now = new Date();
  const nDays = daysInCurrentMonth();
  const session: (number | null)[] = Array(nDays).fill(null);
  const weeklyBest: ({ t: number; pref: boolean; v: number } | null)[] = Array(nDays).fill(null);

  for (const r of rows) {
    if (r.account_id !== accountId) continue;
    const t = new Date(r.taken_at);
    if (t.getMonth() !== now.getMonth() || t.getFullYear() !== now.getFullYear()) continue;
    const d = t.getDate() - 1;
    if (SESSION_RE.test(r.label)) {
      session[d] = Math.max(session[d] ?? 0, r.used_percent);
    } else if (WEEKLY_RE.test(r.label)) {
      const pref = WEEKLY_ALL_RE.test(r.label);
      const cur = weeklyBest[d];
      if (!cur || (pref && !cur.pref) || (pref === cur.pref && t.getTime() >= cur.t)) {
        weeklyBest[d] = { t: t.getTime(), pref, v: r.used_percent };
      }
    }
  }
  return { session, weekly: weeklyBest.map((w) => (w ? w.v : null)) };
}

export default function Dashboard() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [history, setHistory] = useState<HistoryRow[]>([]);

  useEffect(() => {
    const load = () => {
      api.listAccounts().then(setAccounts).catch(console.error);
      api.usageHistory(31).then(setHistory).catch(console.error);
    };
    load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, []);

  const running = accounts.filter((a) => a.status === "running").length;
  const authed = accounts.filter((a) => a.auth_status === "logged_in").length;
  const nDays = daysInCurrentMonth();
  const monthLabel = new Date().toLocaleString(undefined, { month: "short" });

  // peak usage across accounts, for a headline stat
  const peakUsage = Math.max(
    0,
    ...accounts.flatMap((a) => (a.usage_info?.limits ?? []).map((l) => l.used_percent)),
  );

  return (
    <main className="min-h-screen p-5" style={{ background: C.canvas }}>
      <div className="mx-auto max-w-6xl space-y-4">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-semibold" style={{ color: C.ink }}>Overview</h1>
          <div className="flex items-center gap-2 text-[11px]" style={{ color: C.muted }}>
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: C.good }} />
            live · this month · refresh 30s
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Accounts" value={accounts.length} />
          <Stat label="Running" value={running} color={running ? C.good : C.muted} />
          <Stat label="Stopped" value={accounts.length - running} color={C.muted} />
          <Stat label="Authenticated" value={authed} color={authed ? C.good : C.muted} />
          <Stat label="Peak usage" value={peakUsage} unit="%"
                color={peakUsage >= 90 ? C.crit : peakUsage >= 70 ? C.warn : C.blue} />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {accounts.map((a) => {
            const agg = aggregate(history, a.id);
            return (
              <TimeSeries
                key={a.id}
                title={a.name}
                monthLabel={monthLabel}
                days={nDays}
                right={<Link href={`/accounts/${a.id}`} style={{ color: C.muted }}>{a.provider} ↗</Link>}
                series={[
                  { name: a.provider === "claude" ? "session" : "5h limit", color: C.blue, points: agg.session },
                  { name: "weekly", color: C.aqua, points: agg.weekly },
                ]}
              />
            );
          })}
        </div>

        {accounts.length === 0 && (
          <p className="text-sm" style={{ color: C.muted }}>
            No accounts yet — <Link href="/create" style={{ color: C.blue }}>create one</Link>.
          </p>
        )}

        <div>
          <Link href="/accounts" className="text-sm" style={{ color: C.blue }}>Manage accounts →</Link>
        </div>
      </div>
    </main>
  );
}
