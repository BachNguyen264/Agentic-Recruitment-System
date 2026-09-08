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
        // Ramp CỐ Ý THƯA: chỉ khai những sắc độ đang thật sự xuất hiện trong `content`. Tailwind
        // chỉ sinh CSS cho class có mặt trong mã nguồn, nên sắc độ khai mà không dùng KHÔNG tốn
        // byte nào — nhưng nó khiến người đọc tưởng bảng màu rộng hơn thực tế và che mất việc
        // thiết kế thực chất chỉ dùng vài bậc. Cần bậc mới thì THÊM vào đây rồi mới dùng.
        // (Đã bỏ: accent-200/400/500/900, steel-500/600/700/900 và token lẻ `accent2` — 0 nơi dùng.)
        accent: {
          DEFAULT: "#1f6feb", // cobalt — màu nhấn chính
          100: "#dceafe",
          300: "#a9c8fb",
          600: "#1a63de",
          700: "#154fb4",
          800: "#123f8f",
        },
        // Ramp trung tính lạnh (avatar, nền phụ) — đặt tên steel để không đè `neutral` của Tailwind.
        steel: {
          100: "#f4f7fb",
          200: "#e7edf4",
          300: "#d3dde9",
          400: "#b4c2d4",
          800: "#38465b",
        },
      },
      fontFamily: {
        heading: ["var(--font-heading)", "system-ui", "sans-serif"],
        sans: ["var(--font-manrope)", "system-ui", "sans-serif"],
      },
      keyframes: {
        // Chấm "đang chạy trực tiếp" trên dashboard.
        pulseDot: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.28" } },
        // ── Pipeline đa tác tử: ô của node ĐANG chạy phải nhìn ra ngay giữa các ô đứng im ──
        // Vòng sáng lan ra rồi tắt (dùng box-shadow nên KHÔNG chiếm chỗ, không đẩy layout).
        pulseRing: {
          "0%": { boxShadow: "0 0 0 0 rgba(31,111,235,0.42)" },
          "70%": { boxShadow: "0 0 0 10px rgba(31,111,235,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(31,111,235,0)" },
        },
        // Thanh chạy vô định ở đáy ô — "đang làm việc, chưa biết bao lâu" (parser ~9s, ranker ~25s).
        indeterminate: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(320%)" },
        },
        // Hạt chạy dọc mũi tên giữa hai node — cho thấy HƯỚNG đi của hồ sơ.
        flowDot: {
          "0%": { transform: "translateX(-9px)", opacity: "0" },
          "35%,65%": { opacity: "1" },
          "100%": { transform: "translateX(9px)", opacity: "0" },
        },
        // Con số vừa đổi → nảy một nhịp. Kích hoạt bằng `key={count}` (React remount lại phần tử).
        countPop: {
          "0%": { transform: "scale(1)" },
          "38%": { transform: "scale(1.22)" },
          "100%": { transform: "scale(1)" },
        },
      },
      animation: {
        "pulse-dot": "pulseDot 1.6s ease-in-out infinite",
        "pulse-ring": "pulseRing 1.8s ease-out infinite",
        indeterminate: "indeterminate 1.25s ease-in-out infinite",
        "flow-dot": "flowDot 1.1s ease-in-out infinite",
        "count-pop": "countPop 420ms ease-out 1",
      },
    },
  },
  plugins: [],
};

export default config;
