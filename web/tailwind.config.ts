import type { Config } from "tailwindcss";
import colors from "tailwindcss/colors";

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
        // bare token stays the brand hex (text-red / bg-green); spreading the
        // default scale back in keeps red-500 etc. alive. a plain string here
        // wipes the whole scale and you only notice when a class does nothing.
        red: { ...colors.red, DEFAULT: "#FF3D3D" },
        green: { ...colors.green, DEFAULT: "#00E5A0" },
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
