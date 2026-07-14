import type { Metadata, Viewport } from "next";
import { Space_Grotesk, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "GRIDIX — Compute for everything AI",
    template: "%s · GRIDIX",
  },
  description:
    "GRIDIX is a decentralized compute network for the next generation of AI. Run containerized GPU workloads, pay per second in USDC, verify every result on-chain.",
  metadataBase: new URL("https://gridix.compute"),
  openGraph: {
    title: "GRIDIX — Compute for everything AI",
    description: "Decentralized. Scalable. Limitless. Run AI compute on a trustless GPU network.",
    images: ["/assets/assets 1.png"],
  },
  icons: { icon: "/assets/logo.png" },
};

export const viewport: Viewport = {
  themeColor: "#05070a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${spaceGrotesk.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
