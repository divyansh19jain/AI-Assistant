import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI-Assistant – EMR Form Completion",
  description: "EMR-assisted AI voice form completion",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  appleWebApp: { capable: true, statusBarStyle: "default", title: "AI-Assistant" },
};

// iPad/phone-first: own the viewport so safe-area insets activate (viewport-fit=cover)
// and the keyboard resizes the content. Keep maximumScale high — never disable zoom on a
// medical form (accessibility).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  maximumScale: 5,
  themeColor: "#2563eb",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-[100svh] w-full overflow-x-hidden overscroll-y-none bg-gray-50 text-base antialiased">
        {children}
      </body>
    </html>
  );
}
