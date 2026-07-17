import type { Config } from 'tailwindcss'

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        body: ['var(--font-body)', 'sans-serif'],
        display: ['var(--font-display)', 'sans-serif'],
      },
      colors: {
        surface: '#131316',
        hairline: 'rgba(255, 255, 255, 0.07)',
      },
    },
  },
  plugins: [],
} satisfies Config
