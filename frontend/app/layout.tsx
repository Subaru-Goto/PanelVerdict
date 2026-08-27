import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PanelVerdict",
  description: "Synthetic-panel A/B testing for creative variants",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
