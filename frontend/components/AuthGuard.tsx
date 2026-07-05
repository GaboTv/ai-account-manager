"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { me, logout } from "@/lib/api";

// The auth cookie is httpOnly, so the client can't read it — it asks the
// backend (/auth/me) who it is. Renders nothing until the check resolves so
// protected content never flashes.
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "authed" | "login">("checking");
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pathname === "/login") {
      setState("login");
      return;
    }
    me()
      .then((r) => {
        if (r.username) setState("authed");
        else router.replace("/login");
      })
      .catch(() => router.replace("/login"));
  }, [pathname, router]);

  if (state === "checking") return null;
  if (state === "login") return <>{children}</>;

  return (
    <>
      <nav className="flex items-center gap-4 border-b p-4">
        <Link href="/" className="font-bold">AI Account Manager</Link>
        <Link href="/accounts">Accounts</Link>
        <Link href="/create">New account</Link>
        <Link href="/users">Users</Link>
        <button
          className="ml-auto text-sm text-red-600"
          onClick={async () => { await logout(); router.replace("/login"); }}
        >
          Log out
        </button>
      </nav>
      {children}
    </>
  );
}
