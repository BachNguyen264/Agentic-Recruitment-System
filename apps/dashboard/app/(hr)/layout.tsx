"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, logout } from "@/lib/api";

// Guard khu vực HR (slice 09, PRD §4): mọi trang trong nhóm (hr) — /, /applications, /review, /jobs,
// /cv-check — yêu cầu ĐĂNG NHẬP. Kiểm qua GET /api/auth/me (KHÔNG middleware: cookie httpOnly ở domain
// backend, middleware chạy ở edge frontend không đọc được khi deploy cross-domain → sẽ vỡ lúc deploy).
// Ranh giới THẬT vẫn là require_hr ở backend; guard này chỉ là UX (điều hướng + ẩn nội dung).
// Trang CÔNG KHAI (/login, /apply, /screening) nằm NGOÀI nhóm này → không bị guard.
export default function HrLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const qc = useQueryClient();

  const { data: me, isLoading, isError, refetch } = useQuery({
    queryKey: ["me"],
    queryFn: getMe,
    retry: false,
  });

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
    return <div className="p-8 text-sm text-slate-500">Đang kiểm tra phiên đăng nhập…</div>;
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
          className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Thử lại
        </button>
      </div>
    );
  }

  // me === null: đang redirect (useEffect) — không nháy nội dung HR.
  if (!me) return null;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-3 px-8 py-3">
          <Link href="/" className="text-sm font-semibold tracking-tight text-slate-900">
            ARS · HR
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500">{me.email}</span>
            <button
              type="button"
              onClick={() => logoutMutation.mutate()}
              disabled={logoutMutation.isPending}
              className="rounded-md border border-slate-300 px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
            >
              {logoutMutation.isPending ? "Đang thoát…" : "Đăng xuất"}
            </button>
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
