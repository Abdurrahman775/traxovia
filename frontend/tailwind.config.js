/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:  'var(--color-bg)',
        s1:  'var(--color-s1)',
        s2:  'var(--color-s2)',
        s3:  'var(--color-s3)',
        cy:  'var(--color-amber)',
        gd:  '#f0b429',
        rd:  '#e8544f',
        bl:  '#5b8def',
        tx:  'var(--color-tx)',
        tx2: 'var(--color-tx2)',
        em:  'var(--color-emerald)',
      },
      fontFamily: {
        sans:  ['Figtree', 'sans-serif'],
        head:  ['Syne', 'sans-serif'],
        mono:  ['"IBM Plex Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
}
