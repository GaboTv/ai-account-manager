"use client";
import { useState } from "react";
import { api, Account, AuthStart } from "@/lib/api";
import Terminal from "./Terminal";

export default function LoginModal({ account, auth, onClose }: {
  account: Account;
  auth: AuthStart;
  onClose: () => void;
}) {
  const [code, setCode] = useState("");
  const [status, setStatus] = useState(auth.status);

  const submitCode = async () => {
    await api.authInput(account.id, auth.session_id, code);
    setStatus("verifying");
    setCode("");
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-black/50">
      <div className="w-[720px] space-y-4 rounded-lg bg-white p-6 dark:bg-gray-900">
        <div className="flex justify-between">
          <h2 className="text-lg font-bold">Login — {account.name} ({auth.provider})</h2>
          <button onClick={onClose}>✕</button>
        </div>

        <div className="rounded border p-3 text-sm">
          <div>Status: <b>{status}</b> · Method: {auth.method}</div>
          {auth.login_url && (
            <div className="mt-2">
              Open:{" "}
              <a className="break-all text-blue-600 underline" href={auth.login_url} target="_blank" rel="noreferrer">
                {auth.login_url}
              </a>
            </div>
          )}
          {auth.user_code && (
            <div className="mt-2">
              Enter code: <code className="rounded bg-gray-100 px-2 py-1 text-lg dark:bg-gray-800">{auth.user_code}</code>
            </div>
          )}
          {auth.method === "browser" && (
            <div className="mt-2 text-gray-500">
              After logging in, your browser will land on a{" "}
              <code>localhost</code> page that fails to load — copy that full
              URL from the address bar and paste it below.
            </div>
          )}
        </div>

        <Terminal sessionId={auth.session_id} kind="auth" />

        <div className="flex gap-2">
          <input
            className="flex-1 rounded border p-2"
            placeholder="Paste authorization code or the localhost callback URL here"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <button className="rounded bg-blue-600 px-4 text-white" onClick={submitCode} disabled={!code}>
            Submit code
          </button>
        </div>
      </div>
    </div>
  );
}
