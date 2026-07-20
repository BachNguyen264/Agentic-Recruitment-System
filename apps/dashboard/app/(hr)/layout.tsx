"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApplicationListItem } from "@ars/shared-types";
import { Logo } from "@/components/Logo";
import { getApplications, getMe, logout } from "@/lib/api";

// Guard khu vực HR (slice 09, PRD §4): mọi trang trong nhóm (hr) — /, /applications, /review, /jobs,
// /cv-check — yêu cầu ĐĂNG NHẬP. Kiểm qua GET /api/auth/me (KHÔNG middleware: cookie httpOnly ở domain
// backend, middleware chạy ở edge frontend không đọc được khi deploy cross-domain → sẽ vỡ lúc deploy).
// Ranh giới THẬT vẫn là require_hr ở backend; guard này chỉ là UX (điều hướng + ẩn nội dung).
// Trang CÔNG KHAI (/login, /apply, /screening) nằm NGOÀI nhóm này → không bị guard.
//
// UI redesign: guard giữ NGUYÊN logic; phần hiển thị đổi sang shell sidebar cố định (236px) theo
// bản thiết kế — điều hướng luôn thấy, không còn link "← Về dashboard" rải rác từng trang.

type NavItem = { href: string; label: string; icon: React.ReactNode; exact?: boolean };

const ICON = "h-[17px] w-[17px]";
const strokeProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

// 5 mục — "Thống kê" của bản thiết kế tạm bỏ (hệ thống chưa có analytics thật; không dựng màn giả).
const NAV: NavItem[] = [
  {
    href: "/",
    label: "Bảng điều hành",
    exact: true,
    icon: (
      <svg viewBox="0 0 24 24" className={ICON} {...strokeProps}>
        <rect width="7" height="9" x="3" y="3" rx="1" />
        <rect width="7" height="5" x="14" y="3" rx="1" />
        <rect width="7" height="9" x="14" y="12" rx="1" />
        <rect width="7" height="5" x="3" y="16" rx="1" />
      </svg>
    ),
  },
  {
    href: "/applications",
    label: "Ứng viên",
    icon: (
      <svg viewBox="0 0 24 24" className={ICON} {...strokeProps}>
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    href: "/review",
    label: "Hàng đợi review",
    icon: (
      <svg viewBox="0 0 24 24" className={ICON} {...strokeProps}>
        <path d="M11 12H3" />
        <path d="M16 6H3" />
        <path d="M16 18H3" />
        <path d="m18 9 3 3-3 3" />
      </svg>
    ),
  },
  {
    href: "/jobs",
    label: "Tin tuyển dụng",
    icon: (
      <svg viewBox="0 0 24 24" className={ICON} {...strokeProps}>
        <path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
        <rect width="20" height="14" x="2" y="6" rx="2" />
      </svg>
    ),
  },
  {
    href: "/cv-check",
    label: "Kiểm tra CV",
    icon: (
      <svg viewBox="0 0 24 24" className={ICON} {...strokeProps}>
        <path d="M20 10V7l-5-5H6a2 2 0 0 0-2 2v16c0 1.1.9 2 2 2h4" />
        <path d="M14 2v4a2 2 0 0 0 2 2h4" />
        <circle cx="16" cy="17" r="3" />
        <path d="m21 22-1.5-1.5" />
      </svg>
    ),
  },
];

function initialsOf(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  const letters = parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return (letters || "HR").toUpperCase();
}

export default function HrLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();

  const { data: me, isLoading, isError, refetch } = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
    retry: false,
  });

  // Badge "Hàng đợi review": số ca PENDING_REVIEW (PRD §12.4 FR-NOTI-2). Dùng chung queryKey
  // ["applications"] với /review + /applications → duyệt xong badge tự giảm.
  const { data: apps } = useQuery<ApplicationListItem[]>({
    queryKey: ["applications"],
    queryFn: getApplications,
    refetchInterval: 5000,
    enabled: !!me,
  });
  const reviewCount = (apps ?? []).filter((a) => a.status === "PENDING_REVIEW").length;

  // Điều hướng trên điện thoại: sidebar thành ngăn kéo (PRD §6 — HR cài PWA lên máy điện thoại).
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => setNavOpen(false), [pathname]); // đổi trang → đóng ngăn kéo
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  // Chưa đăng nhập (me === null) → về /login kèm ?next để quay lại sau khi đăng nhập.
  useEffect(() => {
    if (!isLoading && me === null) {
      const next = encodeURIComponent(pathname || "/");
      router.replace(`/login?next=${next}`);
    }
  }, [isLoading, me, pathname, router]);

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      await qc.clear(); // bỏ mọi cache HR (không rò dữ liệu sang phiên/đăng nhập sau).
      router.replace("/login");
    },
  });

  if (isLoading) {
    return <div className="p-8 text-sm text-ink/50">Đang kiểm tra phiên đăng nhập…</div>;
  }

  // Lỗi mạng (backend sập) — KHÁC với 401 (đã redirect). Cho thử lại, không kẹt màn trắng.
  if (isError) {
    return (
      <div className="mx-auto max-w-md space-y-3 p-8 text-center">
        <p className="text-sm text-red-600">
          Không kết nối được máy chủ. Backend đã chạy ở :8000 chưa?
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded-lg border-2 border-divider px-4 py-2 text-sm font-semibold hover:bg-ink/5"
        >
          Thử lại
        </button>
      </div>
    );
  }

  // me === null: đang redirect (useEffect) — không nháy nội dung HR.
  if (!me) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-canvas">
      {/* Nền mờ khi mở ngăn kéo (chỉ điện thoại) */}
      {navOpen && (
        <button
          type="button"
          aria-label="Đóng menu"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-30 bg-ink/40 lg:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[236px] flex-none flex-col border-r-2 border-divider bg-canvas transition-transform duration-200 lg:static lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="px-4 pb-3 pt-4">
          <Logo suffix="HR" subtitle="Bảng điều hành tuyển dụng" />
        </div>

        <nav className="flex flex-col gap-0.5 p-2">
          {NAV.map((item) => {
            const active = item.exact ? pathname === item.href : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-[11px] border-l-[3px] py-2.5 pl-2.5 pr-3 text-sm transition-colors ${
                  active
                    ? "border-accent font-bold text-accent"
                    : "border-transparent text-ink hover:bg-ink/[0.06]"
                }`}
              >
                {item.icon}
                <span>{item.label}</span>
                {item.href === "/review" && reviewCount > 0 && (
                  <span
                    aria-label={`${reviewCount} hồ sơ chờ duyệt`}
                    className="ml-auto inline-flex h-5 min-w-[20px] items-center justify-center rounded px-1.5 text-xs font-bold text-white"
                    style={{ background: "#1f6feb" }}
                  >
                    {reviewCount}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t-2 border-divider px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-ink font-heading text-[13px] font-bold text-canvas">
              {initialsOf(me.email)}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-semibold">{me.email.split("@")[0]}</p>
              <p className="truncate text-xs text-ink/50">{me.email}</p>
            </div>
            <button
              type="button"
              onClick={() => logoutMutation.mutate()}
              disabled={logoutMutation.isPending}
              title="Đăng xuất"
              aria-label="Đăng xuất"
              className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border-2 border-divider text-ink/70 hover:bg-ink/5 hover:text-ink disabled:opacity-50"
            >
              <svg viewBox="0 0 24 24" className="h-[15px] w-[15px]" {...strokeProps}>
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" x2="9" y1="12" y2="12" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Thanh trên — CHỈ điện thoại (dưới lg sidebar ẩn thành ngăn kéo) */}
        <div className="flex flex-none items-center gap-3 border-b-2 border-divider px-4 py-2.5 lg:hidden">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Mở menu điều hướng"
            aria-expanded={navOpen}
            className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border-2 border-divider hover:bg-ink/5"
          >
            <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" {...strokeProps}>
              <path d="M4 6h16" />
              <path d="M4 12h16" />
              <path d="M4 18h16" />
            </svg>
          </button>
          <Logo size={24} suffix="HR" />
          {reviewCount > 0 && (
            <Link
              href="/review"
              aria-label={`${reviewCount} hồ sơ chờ duyệt`}
              className="ml-auto inline-flex h-6 min-w-[24px] items-center justify-center rounded bg-accent px-2 text-xs font-bold text-white"
            >
              {reviewCount}
            </Link>
          )}
        </div>

        <main className="ars-scroll min-h-0 flex-1 overflow-y-auto bg-canvas">{children}</main>
      </div>
    </div>
  );
}
