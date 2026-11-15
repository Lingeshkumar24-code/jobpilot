/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        panel: "var(--panel)",
        "panel-raised": "var(--panel-raised)",
        line: "var(--line)",
        paper: "var(--paper)",
        muted: "var(--muted)",
        amber: "var(--amber)",
        signal: "var(--signal)",
        danger: "var(--danger)",
      },
      fontFamily: {
        display: ["var(--font-display)", "sans-serif"],
        sans: ["var(--font-sans)", "sans-serif"],
        mono: ["var(--font-mono)", "monospace"],
      },
    },
  },
  plugins: [],
};
