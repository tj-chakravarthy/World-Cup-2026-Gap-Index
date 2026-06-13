import type { Config } from "tailwindcss";

// Design tokens — locked (PLAN.md §7.1). Do not change without updating the plan.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        black: "#0A0A0F",
        surface: "#111118",
        raised: "#1C1C28",
        volt: "#E8FF00",
        red: "#FF3D3D",
        green: "#00E5A0",
        muted: "#8B8B9E",
        border: "rgba(255,255,255,0.07)",
      },
      fontFamily: {
        display: ["var(--font-barlow-condensed)", "sans-serif"],
        body: ["var(--font-barlow)", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
