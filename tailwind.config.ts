import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#2a1b16",
        pine: "#a86f1f",
        moss: "#c89b3c",
        cinnabar: "#972d17",
        paper: "#f7f1e7",
        cloud: "#fffaf2"
      },
      boxShadow: {
        soft: "0 18px 48px rgba(67, 39, 24, 0.12)"
      }
    }
  },
  plugins: []
};

export default config;
