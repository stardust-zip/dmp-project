import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AuthGate } from "@/components/auth/auth-gate";
import { AuthProvider } from "@/components/auth/auth-provider";
import { AppShell } from "@/components/common/app-shell";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: "Data Management Platform",
  description: "Energy management dashboard for anomaly detection and forecasting.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <AuthGate>
            <AppShell>{children}</AppShell>
          </AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
