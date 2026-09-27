/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Soft dark theme palette — never pure black
        'base': '#121212',         // Page background
        'surface': '#1e293b',      // Card/panel background
        'surface-2': '#263348',    // Slightly elevated surface
        'surface-3': '#2d3f57',    // Hover states
        'border': '#334155',       // Subtle borders
        'primary': '#38bdf8',      // Sky blue accent
        'primary-dim': '#0ea5e9',  // Darker accent variant
        'success': '#34d399',      // Green for Start button
        'danger': '#f87171',       // Red for Stop button
        'sinhala': '#a78bfa',      // Purple — Line 1 Sinhala
        'tamil': '#fbbf24',        // Amber — Line 2 Tamil
        'original': '#94a3b8',     // Slate — Line 3 Original
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-up': 'slideUp 0.25s ease-out',
        'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
        'spin-slow': 'spin 3s linear infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
      },
    },
  },
  plugins: [],
}
