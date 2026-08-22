/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0B0F19',
        panel: 'rgba(25, 33, 48, 0.7)',
        neonGreen: '#00E676',
        neonRed: '#FF3D00',
        textMuted: '#8A95A5',
      },
      backdropBlur: {
        xs: '2px',
      }
    },
  },
  plugins: [],
}
