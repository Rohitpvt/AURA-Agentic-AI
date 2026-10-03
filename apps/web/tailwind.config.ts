import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        aura: {
          canvas: '#090D16',
          surface: '#111726',
          elevated: '#192238',
          subtle: '#222E4B',
          cyan: '#06B6D4',
          violet: '#8B5CF6',
          low: '#10B981',
          med: '#3B82F6',
          high: '#F59E0B',
          crit: '#EF4444',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderColor: {
        'aura-subtle': 'rgba(255, 255, 255, 0.08)',
        'aura-strong': 'rgba(255, 255, 255, 0.16)',
      },
      boxShadow: {
        'aura-glow-cyan': '0 0 20px -5px rgba(6, 182, 212, 0.3)',
        'aura-glow-violet': '0 0 20px -5px rgba(139, 92, 246, 0.3)',
        'aura-glow-amber': '0 0 20px -5px rgba(245, 158, 11, 0.3)',
        'aura-glow-rose': '0 0 20px -5px rgba(239, 68, 68, 0.3)',
      },
    },
  },
  plugins: [],
};

export default config;
