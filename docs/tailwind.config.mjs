import starlightPlugin from "@astrojs/starlight-tailwind";
const thunderbird = {
  50: "#fef3f2",
  100: "#ffe3e1",
  200: "#ffcbc8",
  300: "#ffa8a2",
  400: "#fd756c",
  500: "#f54a3e",
  600: "#e32b1f",
  700: "#c42217",
  800: "#9e1f16",
  900: "#832019",
  950: "#470c08",
};

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}"],
  theme: {
    extend: {
      colors: {
        accent: thunderbird,
      },
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"'],
      },
    },
  },
  plugins: [starlightPlugin()],
};

