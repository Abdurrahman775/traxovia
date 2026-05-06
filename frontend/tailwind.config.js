/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:  '#05080f',
        s1:  '#080d18',
        s2:  '#0c1220',
        s3:  '#101828',
        cy:  '#00e5cc',
        gd:  '#f0b429',
        rd:  '#ff3d5a',
        bl:  '#4f8ef7',
        tx:  '#dde4f0',
        tx2: '#8899b4',
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
