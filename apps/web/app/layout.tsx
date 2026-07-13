import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";

import { AppFrame } from "@/components/app-frame";
import { AuthGate } from "@/components/auth-gate";
import { ConnectionProvider } from "@/components/connection-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "AWS Collaboration Dashboard",
  description: "A monorepo FinOps portfolio app with a Compose MVP and Kubernetes runway."
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<div className="page-loading">Loading dashboard…</div>}>
          <AuthGate>
            <ConnectionProvider>
              <AppFrame>{children}</AppFrame>
            </ConnectionProvider>
          </AuthGate>
        </Suspense>
      </body>
    </html>
  );
}
