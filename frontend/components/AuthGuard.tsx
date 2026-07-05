"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getToken, clearToken } from "@/lib/api";

// Client-side guard: the token lives in localStorage, so routing decisions
// must happen in the browser. Renders nothing until the check resolves to
// avoid flashing protected content.
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "authed" | "login">("checking");
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pathname === "/login") {
      setState("login");
    } else if (!getToken()) {
      router.replace("/login");
    } else {
      setState("authed");
    }
  }, [pathname, router]);

  if (state === "checking") return null;
  if (state === "login") return <>{children}</>;

  return (
    <>
      <nav className="flex items-center gap-4 border-b p-4">
        <Link href="/" className="font-bold">AI Account Manager</Link>
        <Link href="/accounts">Accounts</Link>
        <Link href="/create">New account</Link>
        <button
          className="ml-auto text-sm text-red-600"
          onClick={() => { clearToken(); router.replace("/login"); }}
        >
          Log out
        </button>
      </nav>
      {children}
    </>
  );
}
