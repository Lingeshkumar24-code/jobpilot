import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "JobPilot AI",
  description: "AI-powered job discovery and application assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans">
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <TopBar />
            <main className="flex-1 px-6 py-6">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
