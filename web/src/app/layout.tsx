import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MidiMagic — Audio & YouTube to MIDI",
  description:
    "Ubah MP3 atau tautan YouTube menjadi MIDI, lalu mainkan di piano visualizer ala Synthesia dengan not balok, stem separation, dan synth multi-instrumen.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const,
  themeColor: "#05060c",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id">
      <body className="bg-[#05060c] antialiased">{children}</body>
    </html>
  );
}
