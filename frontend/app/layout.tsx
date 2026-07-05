import "./globals.css";
import AuthGuard from "@/components/AuthGuard";

export const metadata = { title: "AI Account Manager" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthGuard>{children}</AuthGuard>
      </body>
    </html>
  );
}
