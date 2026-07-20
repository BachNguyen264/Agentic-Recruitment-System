// Nguyên thủy giao diện dùng chung — dịch từ hệ thiết kế (nút/thẻ/ô nhập/tiêu đề trang).
// Tailwind THUẦN, tự viết (CLAUDE.md: KHÔNG thêm thư viện UI). Dùng lại ở mọi màn HR + công khai
// để khoảng cách/màu/bo góc nhất quán, không phải chép lại chuỗi class ở từng trang.

const BTN_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-lg text-sm font-semibold leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-45";

const BTN_VARIANT = {
  primary: "bg-accent px-3.5 py-2 text-white hover:bg-accent-600 active:bg-accent-700",
  secondary: "border-2 border-divider px-3.5 py-2 hover:bg-ink/[0.07] active:bg-ink/[0.12]",
  ghost: "px-1.5 py-1 text-accent hover:bg-accent/10 active:bg-accent/[0.18]",
  danger: "border-2 border-red-300 px-3.5 py-2 text-red-700 hover:bg-red-50",
} as const;

export type BtnVariant = keyof typeof BTN_VARIANT;

/** Class cho nút. Dùng được cho cả <button> lẫn <Link> (nên trả class thay vì bọc component). */
export function btn(variant: BtnVariant = "secondary", extra = ""): string {
  return `${BTN_BASE} ${BTN_VARIANT[variant]} ${extra}`.trim();
}

/** Nút chỉ có icon — ô vuông 36px. */
export function btnIcon(variant: BtnVariant = "secondary", extra = ""): string {
  return `${BTN_BASE} ${BTN_VARIANT[variant]} !px-0 !py-0 h-9 w-9 flex-none ${extra}`.trim();
}

const TAG_TONE = {
  accent: "bg-accent-100 text-accent-800",
  neutral: "bg-steel-100 text-steel-800",
  outline: "border border-accent text-accent",
  ok: "bg-emerald-100 text-emerald-800",
  warn: "bg-amber-100 text-amber-900",
  danger: "bg-red-100 text-red-800",
} as const;

export type TagTone = keyof typeof TAG_TONE;

export function Tag({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: TagTone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded px-2.5 py-0.5 text-[11px] font-semibold tracking-[0.02em] ${TAG_TONE[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/** Ô nhập — nền surface, viền 2px, bo 8px (khớp thiết kế). */
export const inputClass =
  "w-full min-h-9 rounded-lg border-2 border-divider bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-ink/40 hover:border-ink/40 focus-visible:border-accent focus-visible:outline-none";

export function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-xs font-semibold text-ink/70">
        {label}
        {required && <span className="text-accent"> *</span>}
      </label>
      {children}
      {hint && <p className="mt-1.5 text-xs text-ink/45">{hint}</p>}
    </div>
  );
}

/** Đầu trang chuẩn: nhãn nhỏ (eyebrow) → tiêu đề → mô tả, kèm chỗ đặt nút hành động. */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow mb-1.5">{eyebrow}</p>
          <h1 className="text-[26px] sm:text-[34px]">{title}</h1>
        </div>
        {actions}
      </div>
      {description && (
        <p className="mt-2 max-w-[70ch] text-[13px] leading-relaxed text-ink/55">{description}</p>
      )}
    </header>
  );
}

/** Trạng thái rỗng — viền đứt, thông điệp hướng hành động (không phải lời xin lỗi). */
export function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border-2 border-dashed border-divider px-6 py-10 text-center text-[13px] text-ink/50">
      {children}
    </div>
  );
}

/** Công tắc bật/tắt (gate) — role="switch" để trình đọc màn hình hiểu đúng. */
export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2.5 text-left text-[13px] disabled:opacity-50"
    >
      <span
        aria-hidden
        className={`relative h-5 w-9 flex-none rounded-full transition-colors ${
          checked ? "bg-accent" : "bg-steel-300"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "translate-x-[18px]" : "translate-x-0.5"
          }`}
        />
      </span>
      <span>{label}</span>
    </button>
  );
}

/** Nút "quay lại" dạng ghost ở đầu trang chi tiết/biểu mẫu. */
export function BackArrow() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-[15px] w-[15px]"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="m12 19-7-7 7-7" />
      <path d="M19 12H5" />
    </svg>
  );
}
