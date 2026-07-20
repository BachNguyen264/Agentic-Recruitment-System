// Dấu hiệu thương hiệu HireFlow: hai thanh dọc + đường luồng có mũi tên ở giữa — hồ sơ ứng viên
// chảy qua pipeline. Dùng lại ở sidebar HR, trang đăng nhập và cổng công khai.
export function LogoMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <span
      aria-hidden
      style={{ width: size, height: size }}
      className={`flex flex-none items-center justify-center rounded-lg bg-accent ${className}`}
    >
      <svg
        width={size * 0.64}
        height={size * 0.64}
        viewBox="0 0 100 100"
        fill="#ffffff"
        role="presentation"
      >
        <rect x="16" y="10" width="15" height="80" rx="4" />
        <rect x="69" y="10" width="15" height="80" rx="4" />
        <circle cx="35" cy="64" r="6.5" />
        <polyline
          points="35,64 45,64 58,38 65,38"
          fill="none"
          stroke="#ffffff"
          strokeWidth="10"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <polygon points="61,30 75,38 61,46" />
      </svg>
    </span>
  );
}

// Khối logo + chữ, dùng ở đầu sidebar / trang công khai.
export function Logo({
  size = 28,
  wordmark = "HireFlow",
  suffix,
  subtitle,
}: {
  size?: number;
  wordmark?: string;
  suffix?: string;
  subtitle?: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2.5">
        <LogoMark size={size} />
        <span className="font-heading text-[18px] font-bold leading-none tracking-tight">
          {wordmark}
          {suffix && <span className="text-ink/45"> · {suffix}</span>}
        </span>
      </div>
      {subtitle && <p className="mt-1.5 text-xs text-ink/50">{subtitle}</p>}
    </div>
  );
}
