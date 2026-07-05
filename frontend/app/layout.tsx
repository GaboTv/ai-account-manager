import "./globals.css";
import Link from "next/link";

export const metadata = { title: "AI Account Manager" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav className="border-b p-4 space-x-4">
          <Link href="/" className="font-bold">AI Account Manager</Link>
          <Link href="/accounts">Accounts</Link>
          <Link href="/create">New account</Link>
        </nav>
        {children}
      </body>
    </html>
  );
}
