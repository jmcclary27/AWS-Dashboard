import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppFrame } from "@/components/app-frame";
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
        <ConnectionProvider>
          <AppFrame>{children}</AppFrame>
        </ConnectionProvider>
      </body>
    </html>
  );
}
