"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Terminal from "@/components/Terminal";
import { api } from "@/lib/api";

export default function TerminalPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const [msg, setMsg] = useState("");

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Session {sessionId.slice(0, 8)}</h1>
        <div className="space-x-2">
          <button className="rounded border px-3 py-1" onClick={() => api.slash(sessionId, "/usage")}>/usage</button>
          <button className="rounded border px-3 py-1" onClick={() => api.slash(sessionId, "/status")}>/status</button>
          <button
            className="rounded border border-red-500 px-3 py-1 text-red-600"
            onClick={async () => { await api.closeSession(sessionId); router.push("/accounts"); }}
          >
            Close session
          </button>
        </div>
      </div>

      <Terminal sessionId={sessionId} />

      <form
        className="flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!msg) return;
          if (!confirm("Sending a message runs the model and consumes account credits. Continue?")) return;
          await api.send(sessionId, msg);
          setMsg("");
        }}
      >
        <input
          className="flex-1 rounded border p-2"
          placeholder="Send a custom message… (consumes credits)"
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
        />
        <button className="rounded bg-amber-600 px-4 text-white">Send (uses credits)</button>
      </form>
      <p className="text-xs text-gray-400">
        The <b>/usage</b> and <b>/status</b> buttons above are free. Typing a message here — or in the
        terminal — runs the model and consumes credits.
      </p>
    </main>
  );
}
