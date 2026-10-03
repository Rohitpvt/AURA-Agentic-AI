import type { Metadata } from 'next';
import './globals.css';
import { Providers } from './providers';

export const metadata: Metadata = {
  title: 'AURA — Autonomous Universal Reactive Agent',
  description:
    'High-density dark-mode command center for AURA agentic operating system with zero-cost local inference and deterministic HITL governance.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-aura-canvas text-slate-100 antialiased font-sans min-h-screen">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
