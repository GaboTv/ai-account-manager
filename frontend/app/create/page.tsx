"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, Account } from "@/lib/api";
import Terminal from "@/components/Terminal";

const PROVIDERS = [
  {
    id: "claude" as const,
    title: "Claude Code",
    blurb: "Anthropic's coding CLI. In the terminal: pick a theme, choose the subscription account, open the URL, then paste the code back.",
  },
  {
    id: "codex" as const,
    title: "Codex CLI",
    blurb: "OpenAI's coding CLI. Browser login redirects to a localhost URL — paste that URL into the field to finish.",
  },
  {
    id: "aiprimetech" as const,
    title: "AI Prime Tech",
    blurb: "Drop-in Claude API replacement (aiprimetech.io). No login — just paste your API key. Uses the Claude Code CLI.",
  },
];

type Step = "form" | "creating" | "terminal" | "done";

export default function CreatePage() {
  const [provider, setProvider] = useState<"claude" | "codex" | "aiprimetech">("claude");
  const [name, setName] = useState("");
  const [step, setStep] = useState<Step>("form");
  const [pct, setPct] = useState(0);
  const [progressLabel, setProgressLabel] = useState("");
  const [account, setAccount] = useState<Account | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [needsCallback, setNeedsCallback] = useState(false);
  const [callbackUrl, setCallbackUrl] = useState("");
  const [callbackMsg, setCallbackMsg] = useState<string | null>(null);
  const [codeInput, setCodeInput] = useState("");
  const [codeMsg, setCodeMsg] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://aiprimetech.io");
  const [keyMsg, setKeyMsg] = useState<string | null>(null);
  const [authResult, setAuthResult] = useState<string | null>(null);
  const router = useRouter();

  const bump = (p: number, label: string) => {
    setPct(p);
    setProgressLabel(label);
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setStep("creating");
    try {
      bump(15, "Creating account…");
      // Lean defaults: idle runners are ~7 MiB (CLI procs reaped); the cap
      // only needs to cover a transient TUI boot (~400-500 MiB).
      const acct = await api.createAccount({ provider, name, cpu_limit: 1, memory_limit_mb: 768 });
      setAccount(acct);

      bump(45, "Creating container and volumes…");
      await api.container(acct.id, "create");

      bump(75, "Starting container…");
      await api.container(acct.id, "start");

      // aiprimetech has no login terminal — go straight to the API-key form.
      if (provider !== "aiprimetech") {
        bump(90, "Launching CLI…");
        const s = await api.setupSession(acct.id);
        setSessionId(s.session_id);
        setNeedsCallback(s.needs_callback_field);
      }

      bump(100, "Ready");
      setTimeout(() => setStep("terminal"), 400); // let the bar reach 100
    } catch (err) {
      alert((err as Error).message);
      setStep("form");
      setPct(0);
    }
  };

  const sendCode = async () => {
    if (!sessionId || !codeInput) return;
    setCodeMsg("Sending…");
    try {
      await api.sessionInput(sessionId, codeInput); // sends text + Enter to the PTY
      setCodeMsg("✅ Sent to terminal — watch it complete login, then Verify.");
      setCodeInput("");
    } catch (e) {
      setCodeMsg(`❌ ${(e as Error).message}`);
    }
  };

  const saveKey = async () => {
    if (!account || !apiKey) return;
    setKeyMsg("Saving…");
    try {
      await api.setKey(account.id, apiKey, baseUrl);
      setApiKey("");
      setAuthResult("✅ Logged in");
      setStep("done");
    } catch (e) {
      setKeyMsg(`❌ ${(e as Error).message}`);
    }
  };

  const submitCallback = async () => {
    if (!account) return;
    setCallbackMsg("Forwarding…");
    try {
      await api.setupCallback(account.id, callbackUrl);
      setCallbackMsg("✅ URL forwarded — watch the terminal complete login.");
      setCallbackUrl("");
    } catch (e) {
      setCallbackMsg(`❌ ${(e as Error).message}`);
    }
  };

  const verify = async () => {
    if (!account) return;
    setAuthResult("checking…");
    try {
      const r = await api.authStatus(account.id);
      if (r.logged_in) {
        setAuthResult("✅ Logged in");
        setStep("done");
      } else {
        setAuthResult("❌ Not logged in yet — finish the login in the terminal, then verify again.");
      }
    } catch (e) {
      setAuthResult(`error: ${(e as Error).message}`);
    }
  };

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">New AI account</h1>
        <Steps step={step} />
      </div>

      {step === "form" && (
        <form onSubmit={create} className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setProvider(p.id)}
                className={`rounded-lg border p-4 text-left transition ${
                  provider === p.id ? "border-blue-600 ring-1 ring-blue-600" : "hover:border-gray-400"
                }`}
              >
                <div className="font-semibold">{p.title}</div>
                <div className="mt-1 text-sm text-gray-500">{p.blurb}</div>
              </button>
            ))}
          </div>
          <input
            className="w-full rounded border p-2"
            placeholder={`account name, e.g. ${provider}-main`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            pattern="[a-z0-9][a-z0-9-]{1,30}"
            title="lowercase letters, digits and dashes"
            required
          />
          <button className="rounded bg-blue-600 px-4 py-2 text-white">Create account →</button>
        </form>
      )}

      {step === "creating" && (
        <div className="space-y-3 py-8">
          <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
            <div
              className="h-full rounded-full bg-blue-600 transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex justify-between text-sm text-gray-500">
            <span>{progressLabel}</span>
            <span>{pct}%</span>
          </div>
        </div>
      )}

      {step === "terminal" && account && provider === "aiprimetech" && (
        <div className="space-y-4">
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm dark:border-blue-900 dark:bg-blue-950">
            Paste your AI Prime Tech API key. It's stored only inside this account's
            protected volume (<code>~/.claude/settings.json</code>) — never in the database.
          </div>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              saveKey();
            }}
          >
            <label className="block text-sm">
              Base URL
              <input
                className="mt-1 w-full rounded border p-2 text-sm"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              API key
              <input
                type="password"
                className="mt-1 w-full rounded border p-2 text-sm"
                placeholder="sk-…"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                required
              />
            </label>
            <button
              type="submit"
              className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
              disabled={!apiKey}
            >
              Save key
            </button>
            {keyMsg && <div className="text-sm text-gray-500">{keyMsg}</div>}
          </form>
        </div>
      )}

      {step === "terminal" && account && sessionId && (
        <div className="space-y-4">
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm dark:border-blue-900 dark:bg-blue-950">
            {provider === "claude" ? (
              <ol className="list-decimal space-y-1 pl-5">
                <li>Pick a text style (e.g. <b>2</b> = Dark mode), press Enter.</li>
                <li>Choose <b>1. Claude account with subscription</b>, press Enter.</li>
                <li>Open the printed URL in your browser and authorize.</li>
                <li>Copy the code Claude shows you and paste it in the <b>field below</b>, then press Send (or type it directly in the terminal).</li>
              </ol>
            ) : (
              <ol className="list-decimal space-y-1 pl-5">
                <li>Open the printed URL in your browser and sign in.</li>
                <li>Your browser will land on a <code>localhost</code> page that fails to load.</li>
                <li>Copy that full URL from the address bar and paste it in the field below.</li>
              </ol>
            )}
          </div>

          <Terminal sessionId={sessionId} />

          {needsCallback ? (
            <div className="space-y-1">
              <div className="flex gap-2">
                <input
                  className="flex-1 rounded border p-2 text-sm"
                  placeholder="http://localhost:1455/auth/callback?code=…"
                  value={callbackUrl}
                  onChange={(e) => setCallbackUrl(e.target.value)}
                />
                <button
                  className="rounded bg-blue-600 px-4 text-white disabled:opacity-50"
                  onClick={submitCallback}
                  disabled={!callbackUrl}
                >
                  Submit URL
                </button>
              </div>
              {callbackMsg && <div className="text-sm text-gray-500">{callbackMsg}</div>}
            </div>
          ) : (
            <div className="space-y-1">
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  sendCode();
                }}
              >
                <input
                  className="flex-1 rounded border p-2 text-sm"
                  placeholder="Paste the authorization code here"
                  value={codeInput}
                  onChange={(e) => setCodeInput(e.target.value)}
                />
                <button
                  type="submit"
                  className="rounded bg-blue-600 px-4 text-white disabled:opacity-50"
                  disabled={!codeInput}
                >
                  Send
                </button>
              </form>
              {codeMsg && <div className="text-sm text-gray-500">{codeMsg}</div>}
            </div>
          )}

          <div className="flex items-center gap-3">
            <button className="rounded border px-4 py-2" onClick={verify}>
              Verify login
            </button>
            {authResult && <span className="text-sm">{authResult}</span>}
          </div>
        </div>
      )}

      {step === "done" && account && (
        <div className="space-y-4 rounded-lg border border-green-300 bg-green-50 p-6 dark:border-green-900 dark:bg-green-950">
          <div className="text-lg font-semibold">✅ {account.name} is ready and logged in</div>
          <div className="flex gap-2">
            <Link href={`/accounts/${account.id}`} className="rounded bg-blue-600 px-4 py-2 text-white">
              Open account
            </Link>
            <Link href="/accounts" className="rounded border px-4 py-2">
              All accounts
            </Link>
          </div>
        </div>
      )}
    </main>
  );
}

function Steps({ step }: { step: Step }) {
  const order: Step[] = ["form", "creating", "terminal", "done"];
  const labels = { form: "Name", creating: "Create", terminal: "Login", done: "Done" };
  const idx = order.indexOf(step);
  return (
    <div className="flex items-center gap-1 text-xs text-gray-400">
      {order.map((s, i) => (
        <span key={s} className={i <= idx ? "font-semibold text-blue-600" : ""}>
          {labels[s]}
          {i < order.length - 1 && <span className="mx-1 text-gray-300">›</span>}
        </span>
      ))}
    </div>
  );
}
