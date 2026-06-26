import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#1d4ed8", light: "#3b82f6", dark: "#1e3a8a" },
        ai: {
          50:  "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          violet: "#8b5cf6",
        },
        surface: {
          50:  "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
          300: "#cbd5e1",
          400: "#94a3b8",
          500: "#64748b",
          600: "#475569",
          700: "#334155",
          800: "#1e293b",
          900: "#0f172a",
          950: "#020617",
        },
      },
      keyframes: {
        "fade-slide-up": {
          "0%":   { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "float-in": {
          "0%":   { opacity: "0", transform: "translateY(8px) scale(0.97)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        "pulse-ring": {
          "0%":   { transform: "scale(0.85)", opacity: "0.75" },
          "100%": { transform: "scale(1.9)",  opacity: "0" },
        },
        "wave-bar": {
          "0%, 100%": { transform: "scaleY(0.3)" },
          "50%":      { transform: "scaleY(1)" },
        },
        typing: {
          "0%, 60%, 100%": { transform: "translateY(0)",    opacity: "0.4" },
          "30%":            { transform: "translateY(-5px)", opacity: "1" },
        },
        "orb-glow": {
          "0%, 100%": {
            boxShadow:
              "0 0 14px 3px rgba(99,102,241,0.5), 0 0 28px 6px rgba(139,92,246,0.28)",
          },
          "50%": {
            boxShadow:
              "0 0 22px 6px rgba(99,102,241,0.7), 0 0 44px 12px rgba(139,92,246,0.4)",
          },
        },
        "orb-pulse": {
          "0%, 100%": { transform: "scale(1)" },
          "50%":      { transform: "scale(1.06)" },
        },
      },
      animation: {
        "fade-slide-up": "fade-slide-up 0.4s cubic-bezier(0.22,1,0.36,1) both",
        "float-in":      "float-in 0.35s cubic-bezier(0.22,1,0.36,1) both",
        "pulse-ring":    "pulse-ring 1.4s ease-out infinite",
        "wave-bar":      "wave-bar 0.75s ease-in-out infinite",
        typing:          "typing 1.2s ease-in-out infinite",
        "orb-glow":      "orb-glow 3s ease-in-out infinite",
        "orb-pulse":     "orb-pulse 3s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
