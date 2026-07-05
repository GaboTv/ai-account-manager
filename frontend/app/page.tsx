"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Account } from "@/lib/api";
import DailyUsageChart, { DayPoint } from "@/components/DailyUsageChart";

type HistoryRow = {
  account_id: string;
  name: string;
  provider: string;
  taken_at: string;
  label: string;
  used_percent: number;
};

// Palette reference (dataviz skill): sequential blue for the first context,
// aqua for the second; light/dark steps as documented.
const BLUE = { light: "#2a78d6", dark: "#3987e5" };
const AQUA = { light: "#1baf7a", dark: "#199e70" };

const SESSION_RE = /session|5h/i;
const WEEKLY_ALL_RE = /all models/i;
const WEEKLY_RE = /week/i;

function daysInCurrentMonth(): number {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
}

// Bucket snapshots into day-of-current-month (browser-local dates).
// Session/5h → daily peak; weekly → last snapshot of the day.
function aggregate(rows: HistoryRow[], accountId: string) {
  const now = new Date();
  const nDays = daysInCurrentMonth();
  const sessionMax: (number | null)[] = Array(nDays).fill(null);
  const weeklyBest: ({ t: number; pref: boolean; v: number } | null)[] = Array(nDays).fill(null);

  for (const r of rows) {
    if (r.account_id !== accountId) continue;
    const t = new Date(r.taken_at);
    if (t.getMonth() !== now.getMonth() || t.getFullYear() !== now.getFullYear()) continue;
    const d = t.getDate() - 1;
    if (SESSION_RE.test(r.label)) {
      sessionMax[d] = Math.max(sessionMax[d] ?? 0, r.used_percent);
    } else if (WEEKLY_RE.test(r.label)) {
      // prefer the "all models" gauge when a provider has several weekly
      // ones; among equals, the latest snapshot of the day wins
      const pref = WEEKLY_ALL_RE.test(r.label);
      const cur = weeklyBest[d];
      if (!cur || (pref && !cur.pref) || (pref === cur.pref && t.getTime() >= cur.t)) {
        weeklyBest[d] = { t: t.getTime(), pref, v: r.used_percent };
      }
    }
  }
  const toPoints = (vals: (number | null)[]): DayPoint[] =>
    vals.map((value, i) => ({ day: i + 1, value }));
  return {
    session: toPoints(sessionMax),
    weekly: toPoints(weeklyBest.map((w) => (w ? w.v : null))),
  };
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
    const t = setInterval(load, 5 * 60 * 1000); // backend poller adds a point hourly
    return () => clearInterval(t);
  }, []);

  const running = accounts.filter((a) => a.status === "running").length;
  const authed = accounts.filter((a) => a.auth_status === "logged_in").length;

  const Stat = ({ label, value }: { label: string; value: number }) => (
    <div className="rounded-lg border p-4">
      <div className="text-3xl font-bold">{value}</div>
      <div className="text-sm text-gray-500">{label}</div>
    </div>
  );

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-8">
      <h1 className="text-2xl font-bold">AI Account Manager</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Accounts" value={accounts.length} />
        <Stat label="Running" value={running} />
        <Stat label="Stopped" value={accounts.length - running} />
        <Stat label="Authenticated" value={authed} />
        <Stat label="Need login" value={accounts.length - authed} />
      </div>

      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">Daily usage this month</h2>
        <span className="text-xs text-gray-400">
          auto-collected hourly · session = daily peak, weekly = end of day
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {accounts.map((a) => {
          const agg = aggregate(history, a.id);
          const hasData =
            agg.session.some((p) => p.value !== null) || agg.weekly.some((p) => p.value !== null);
          return (
            <div key={a.id} className="space-y-3 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <Link href={`/accounts/${a.id}`} className="font-semibold text-blue-600">
                  {a.name}
                </Link>
                <span className="text-xs uppercase text-gray-400">{a.provider}</span>
              </div>
              {hasData ? (
                <>
                  <DailyUsageChart
                    title={a.provider === "claude" ? "Session limit — daily peak" : "5h limit — daily peak"}
                    points={agg.session}
                    light={BLUE.light}
                    dark={BLUE.dark}
                  />
                  <DailyUsageChart
                    title="Weekly limit — end of day"
                    points={agg.weekly}
                    light={AQUA.light}
                    dark={AQUA.dark}
                  />
                </>
              ) : (
                <p className="text-sm text-gray-400">
                  No usage data yet — collected automatically every hour while the container runs.
                </p>
              )}
            </div>
          );
        })}
      </div>

      <Link href="/accounts" className="inline-block rounded bg-blue-600 px-4 py-2 text-white">
        Manage accounts →
      </Link>
    </main>
  );
}
