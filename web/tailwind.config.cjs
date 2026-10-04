// Keep the original main theme; build utilities for the ported React sources.
const path = require("node:path");
module.exports = {
  content: [path.join(__dirname, "src/**/*.{ts,tsx}"), path.join(__dirname, "../src/**/*.{ts,tsx}")],
  theme: { extend: {
    colors: { ink: "#2a1b16", pine: "#a86f1f", moss: "#c89b3c", cinnabar: "#972d17", paper: "#f7f1e7", cloud: "#fffaf2" },
    boxShadow: { soft: "0 18px 48px rgba(67, 39, 24, 0.12)" },
  } },
  plugins: [],
};
