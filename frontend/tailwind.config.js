/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Soft dark palette — never pure black.
        base: '#121212',
        surface: '#1e293b',
        'surface-2': '#243044',
        'surface-3': '#2d3b52',
        border: '#334155',
        primary: '#38bdf8',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        // Latin from Inter; Sinhala/Tamil glyphs fall through to Noto, then
        // Windows' built-in Nirmala UI if the web fonts can't load.
        subtitle: ['Inter', '"Noto Sans Sinhala"', '"Noto Sans Tamil"', '"Nirmala UI"', 'system-ui', 'sans-serif'],
      },
      animation: {
        'slide-up': 'slideUp 0.25s ease-out',
        'pulse-soft': 'pulseSoft 1.6s ease-in-out infinite',
      },
      keyframes: {
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
      },
    },
  },
  plugins: [],
}
