import type { Metadata } from "next";
import Link from "next/link";

import { siteUrl } from "@/lib/config";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl()),
  title: { default: "PaperBoard", template: "%s · PaperBoard" },
  description: "分布式的多智能体文献调研平台",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <header className="border-b border-neutral-200 dark:border-neutral-800">
          <div className="mx-auto w-full max-w-3xl px-6 py-4">
            <Link href="/" className="text-lg font-bold">
              PaperBoard
            </Link>
          </div>
        </header>
        <div className="flex flex-1 flex-col">{children}</div>
      </body>
    </html>
  );
}
