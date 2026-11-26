import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PaperBoard",
  description: "分布式的多智能体文献调研平台",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
