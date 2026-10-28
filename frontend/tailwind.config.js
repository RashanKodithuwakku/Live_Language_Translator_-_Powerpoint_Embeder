/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Neutral dark palette, close to a Grok-style surface. Never pure black.
        base: '#0e0e0e',
        surface: '#161616',
        'surface-2': '#1f1f1f',
        'surface-3': '#2a2a2a',
        border: '#333333',
        primary: '#f4f4f5',
        slate: {
          50: '#fafafa',
          100: '#f5f5f5',
          200: '#e5e5e5',
          300: '#d4d4d4',
          400: '#a3a3a3',
          500: '#737373',
          600: '#525252',
          700: '#404040',
          800: '#262626',
          900: '#171717',
          950: '#0a0a0a',
        },
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
