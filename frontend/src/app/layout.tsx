import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Msimulizi — AI Match Intelligence",
  description:
    "Real-time multilingual football match commentary powered by Azure AI.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">{children}</body>
    </html>
  );
}
