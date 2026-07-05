"use client";
import { useCallback, useEffect, useState } from "react";
import { usersApi, User, me } from "@/lib/api";

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [form, setForm] = useState({ username: "", password: "" });
  const [current, setCurrent] = useState<string | null>(null);

  const refresh = useCallback(() => usersApi.list().then(setUsers).catch(console.error), []);
  useEffect(() => {
    refresh();
    me().then((r) => setCurrent(r.username)).catch(() => {});
  }, [refresh]);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await usersApi.create(form.username, form.password);
      setForm({ username: "", password: "" });
      refresh();
    } catch (err) {
      alert((err as Error).message);
    }
  };

  const remove = async (u: User) => {
    if (!confirm(`Delete user ${u.username}?`)) return;
    try {
      await usersApi.remove(u.id);
      refresh();
    } catch (err) {
      alert((err as Error).message);
    }
  };

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <h1 className="text-2xl font-bold">Users</h1>

      <form onSubmit={add} className="flex gap-2">
        <input
          className="flex-1 rounded border p-2"
          placeholder="username"
          value={form.username}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          required
        />
        <input
          type="password"
          className="flex-1 rounded border p-2"
          placeholder="password (min 6)"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          minLength={6}
          required
        />
        <button className="rounded bg-blue-600 px-4 text-white">Add user</button>
      </form>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left"><th className="p-2">Username</th><th>Created</th><th></th></tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-b">
              <td className="p-2 font-medium">
                {u.username}{u.username === current && <span className="ml-2 text-xs text-gray-400">(you)</span>}
              </td>
              <td className="text-gray-500">{u.created_at ? new Date(u.created_at).toLocaleString() : ""}</td>
              <td className="py-2 text-right">
                <button className="text-red-600" onClick={() => remove(u)} disabled={users.length <= 1}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-gray-400">The last remaining user can't be deleted.</p>
    </main>
  );
}
