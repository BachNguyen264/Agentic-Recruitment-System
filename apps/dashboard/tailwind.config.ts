import type { Config } from "tailwindcss";

// UI redesign — hệ token "Marine" từ bản thiết kế (claude.ai/design → handoff bundle).
// Nền trắng lạnh + mực xanh navy + nhấn cobalt; chữ Be Vietnam Pro (tiêu đề) + Manrope (thân).
// (Thiết kế gốc dùng Sora nhưng Sora không có subset tiếng Việt — xem app/layout.tsx.)
// Giữ Tailwind THUẦN (CLAUDE.md: không thêm thư viện UI) — token khai báo ở đây, dùng qua utility.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#ffffff", // nền trang
        surface: "#eef2f7", // nền panel/thẻ
        ink: "#0f1c2e", // chữ chính (navy đậm)
        divider: "rgba(15,28,46,0.22)", // đường kẻ 22% mực — viền panel 2px của thiết kế
        accent: {
          DEFAULT: "#1f6feb", // cobalt — màu nhấn chính
          100: "#dceafe",
          200: "#cfe0fd",
          300: "#a9c8fb",
          400: "#75a4f7",
          500: "#3f82f1",
          600: "#1a63de",
          700: "#154fb4",
          800: "#123f8f",
          900: "#122f63",
        },
        accent2: "#4b8bf5",
        // Ramp trung tính lạnh (avatar, nền phụ) — đặt tên steel để không đè `neutral` của Tailwind.
        steel: {
          100: "#f4f7fb",
          200: "#e7edf4",
          300: "#d3dde9",
          400: "#b4c2d4",
          500: "#93a3b8",
          600: "#6f8098",
          700: "#52627a",
          800: "#38465b",
          900: "#1f2a3d",
        },
      },
      fontFamily: {
        heading: ["var(--font-heading)", "system-ui", "sans-serif"],
        sans: ["var(--font-manrope)", "system-ui", "sans-serif"],
      },
      keyframes: {
        // Chấm "đang chạy trực tiếp" trên dashboard.
        pulseDot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.28" } },
      },
      animation: {
        "pulse-dot": "pulseDot 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
